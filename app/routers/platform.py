# app/routers/platform.py
"""
Platform & Infrastructure Router
  GET  /platform                     — Health check dashboard
  GET  /platform/health              — JSON health data
  GET  /platform/backup              — Trigger manual backup
  GET  /platform/backup/logs         — Backup history
  GET  /platform/changelog           — Changelog page
  POST /platform/changelog/create    — Create changelog entry (super_admin)
  POST /platform/changelog/read/{v}  — Mark version as read
  GET  /platform/search              — Global search JSON
  GET  /platform/audit/export        — Export audit log CSV/PDF

  GET  /tenants                      — List all tenants (super_admin)
  POST /tenants/create               — Create new tenant
  GET  /tenants/{id}                 — Tenant detail + settings
  POST /tenants/{id}/update          — Update tenant branding
  POST /tenants/{id}/toggle          — Activate / deactivate
"""

import io
import os
import csv
import time
import shutil
import asyncio
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, text

from app.database import get_db
from app.models import (
    User, UserRole, AuditLog, Document, Message, KnowledgeChunk,
    Task, Channel, BackupLog, ChangelogEntry, ChangelogRead,
    Tenant, TenantSetting
)
from app.auth import require_user
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["platform"])
templates = Jinja2Templates(directory="app/templates")

BACKUP_DIR = Path("backups")
BACKUP_DIR.mkdir(exist_ok=True)

@router.get("/platform", response_class=HTMLResponse)
async def health_dashboard(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in (UserRole.super_admin, UserRole.admin):
        raise HTTPException(status_code=403)
    return templates.TemplateResponse(request=request, name="platform/health.html", context={
        "user": current_user, "page": "platform",
    })


@router.get("/platform/health")
async def health_data(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """JSON health snapshot — called every 10s by the dashboard."""
    result = {}

    db_ok = False
    db_latency = None
    try:
        t0 = time.perf_counter()
        await db.execute(text("SELECT 1"))
        db_latency = round((time.perf_counter() - t0) * 1000, 1)
        db_ok = True
    except Exception as e:
        result["db_error"] = str(e)

    counts = {}
    for model, label in [
        (User, "users"), (Document, "documents"),
        (Message, "messages"), (KnowledgeChunk, "knowledge_chunks"),
        (Task, "tasks"),
    ]:
        try:
            counts[label] = (await db.execute(select(func.count(model.id)))).scalar() or 0
        except Exception:
            counts[label] = -1

    result["database"] = {
        "ok": db_ok,
        "latency_ms": db_latency,
        "counts": counts,
    }

    ai_ok = False
    ai_model = settings.OLLAMA_MODEL
    try:
        import httpx
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            if r.status_code == 200:
                ai_ok = True
                models = r.json().get("models", [])
                ai_model = models[0]["name"] if models else settings.OLLAMA_MODEL
    except Exception:
        pass

    result["ai"] = {"ok": ai_ok, "model": ai_model, "url": settings.OLLAMA_BASE_URL}

    try:
        disk = shutil.disk_usage("/")
        result["disk"] = {
            "total_gb":  round(disk.total / 1e9, 1),
            "used_gb":   round(disk.used  / 1e9, 1),
            "free_gb":   round(disk.free  / 1e9, 1),
            "pct_used":  round(disk.used  / disk.total * 100, 1),
        }
    except Exception:
        result["disk"] = {}

    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split()
                if parts[0] in ("MemTotal:", "MemAvailable:", "MemFree:"):
                    mem[parts[0].rstrip(":")] = int(parts[1]) * 1024
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        result["memory"] = {
            "total_gb": round(total / 1e9, 2),
            "used_gb":  round((total - avail) / 1e9, 2),
            "free_gb":  round(avail / 1e9, 2),
            "pct_used": round((total - avail) / total * 100, 1) if total else 0,
        }
    except Exception:
        result["memory"] = {}
    try:
        from app.services.websocket_manager import manager
        ws_count = sum(len(v) for v in manager.channel_connections.values())
        result["websockets"] = {"active": ws_count}
    except Exception:
        result["websockets"] = {"active": 0}

    try:
        upload_path = Path(settings.UPLOAD_DIR)
        total_bytes = sum(f.stat().st_size for f in upload_path.rglob("*") if f.is_file())
        result["uploads"] = {"size_mb": round(total_bytes / 1e6, 1)}
    except Exception:
        result["uploads"] = {"size_mb": 0}
    try:
        with open("/proc/uptime") as f:
            uptime_s = float(f.read().split()[0])
        result["uptime_hours"] = round(uptime_s / 3600, 1)
    except Exception:
        result["uptime_hours"] = None

    result["timestamp"] = datetime.utcnow().isoformat()
    return JSONResponse(result)

@router.post("/platform/backup")
async def trigger_backup(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in (UserRole.super_admin, UserRole.admin):
        raise HTTPException(status_code=403)

    log = BackupLog(triggered_by="manual")
    db.add(log)
    await db.commit()
    await db.refresh(log)

    background_tasks.add_task(_run_backup, log.id)
    return JSONResponse({"status": "started", "backup_id": log.id})


async def _run_backup(log_id: int):
    """Run pg_dump and save the result."""
    from app.database import AsyncSessionLocal
    t0 = time.perf_counter()

    async with AsyncSessionLocal() as db:
        log = (await db.execute(select(BackupLog).where(BackupLog.id == log_id))).scalar_one_or_none()
        if not log:
            return

        try:
            db_url = settings.DATABASE_URL 
            clean  = db_url.replace("postgresql+asyncpg://", "postgresql://")

            timestamp  = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            out_file   = BACKUP_DIR / f"boss_backup_{timestamp}.sql.gz"

            cmd = f'pg_dump "{clean}" | gzip > "{out_file}"'
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()

            if proc.returncode == 0:
                size = out_file.stat().st_size
                log.status       = "success"
                log.file_path    = str(out_file)
                log.file_size    = size
                log.duration_s   = round(time.perf_counter() - t0, 2)
                log.completed_at = datetime.utcnow()
                logger.info(f"Backup completed: {out_file} ({size} bytes)")

                await _prune_old_backups()
            else:
                log.status = "failed"
                log.error  = stderr.decode()[:500]
                log.completed_at = datetime.utcnow()
                logger.error(f"Backup failed: {log.error}")

        except Exception as e:
            log.status = "failed"
            log.error  = str(e)
            log.completed_at = datetime.utcnow()
            logger.error(f"Backup exception: {e}")

        await db.commit()


async def _prune_old_backups(retain_days: int = 30):
    """Delete backup files older than retain_days."""
    cutoff = datetime.utcnow() - timedelta(days=retain_days)
    for f in BACKUP_DIR.glob("*.sql.gz"):
        mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            f.unlink()
            logger.info(f"Pruned old backup: {f}")


@router.get("/platform/backup/logs")
async def backup_logs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    logs = (await db.execute(
        select(BackupLog).order_by(BackupLog.created_at.desc()).limit(30)
    )).scalars().all()
    return JSONResponse([{
        "id": l.id, "status": l.status,
        "file_size": l.file_size, "duration_s": l.duration_s,
        "triggered_by": l.triggered_by, "error": l.error,
        "created_at": l.created_at.isoformat() if l.created_at else "",
        "completed_at": l.completed_at.isoformat() if l.completed_at else "",
    } for l in logs])


@router.get("/platform/backup/{backup_id}/download")
async def download_backup(
    backup_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403)
    log = (await db.execute(select(BackupLog).where(BackupLog.id == backup_id))).scalar_one_or_none()
    if not log or not log.file_path:
        raise HTTPException(status_code=404)
    path = Path(log.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup file not found on disk")

    def iter_file():
        with open(path, "rb") as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        iter_file(), media_type="application/gzip",
        headers={"Content-Disposition": f"attachment; filename={path.name}"}
    )

@router.get("/platform/changelog", response_class=HTMLResponse)
async def changelog_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    entries = (await db.execute(
        select(ChangelogEntry)
        .where(ChangelogEntry.is_published == True)
        .order_by(ChangelogEntry.created_at.desc())
    )).scalars().all()

    read_versions = set((await db.execute(
        select(ChangelogRead.version).where(ChangelogRead.user_id == current_user.id)
    )).scalars().all())

    for e in entries:
        if e.version not in read_versions:
            db.add(ChangelogRead(user_id=current_user.id, version=e.version))
    await db.commit()

    return templates.TemplateResponse(request=request, name="platform/changelog.html", context={
        "user": current_user, "page": "platform",
        "entries": entries, "read_versions": read_versions,
    })


@router.post("/platform/changelog/create")
async def create_changelog(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403)
    body = await request.json()
    db.add(ChangelogEntry(
        version=body.get("version", ""),
        title=body.get("title", ""),
        body=body.get("body", ""),
        type=body.get("type", "feature"),
        created_by=current_user.id,
    ))
    await db.commit()
    return JSONResponse({"status": "created"})


@router.get("/platform/changelog/unread-count")
async def changelog_unread(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    total = (await db.execute(
        select(func.count(ChangelogEntry.id)).where(ChangelogEntry.is_published == True)
    )).scalar() or 0
    read = (await db.execute(
        select(func.count(ChangelogRead.id)).where(ChangelogRead.user_id == current_user.id)
    )).scalar() or 0
    return JSONResponse({"unread": max(0, total - read)})

@router.get("/search")
async def global_search(
    q: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if len(q.strip()) < 2:
        return JSONResponse({"results": [], "query": q})

    pattern = f"%{q}%"
    results = []

    msgs = (await db.execute(
        select(Message, User.full_name)
        .join(User, Message.sender_id == User.id)
        .where(Message.content.ilike(pattern), Message.is_deleted == False)
        .limit(5)
    )).all()
    for m, name in msgs:
        results.append({
            "type": "message", "icon": "fa-comment-dots",
            "title": f"{name}: {(m.content or '')[:80]}",
            "subtitle": m.created_at.strftime("%b %d, %Y") if m.created_at else "",
            "url": "/messages",
            "color": "var(--blue)",
        })

    docs = (await db.execute(
        select(Document)
        .where(or_(Document.title.ilike(pattern), Document.content.ilike(pattern)))
        .limit(5)
    )).scalars().all()
    for d in docs:
        results.append({
            "type": "document", "icon": "fa-file-lines",
            "title": d.title,
            "subtitle": f"{d.department} · {d.status.value}",
            "url": "/documents",
            "color": "var(--green)",
        })

    users = (await db.execute(
        select(User)
        .where(or_(User.full_name.ilike(pattern), User.email.ilike(pattern)))
        .limit(4)
    )).scalars().all()
    for u in users:
        results.append({
            "type": "user", "icon": "fa-user",
            "title": u.full_name,
            "subtitle": f"{u.department} · {u.role.value.replace('_',' ').title()}",
            "url": "/directory",
            "color": "var(--purple)",
        })

    # Tasks
    tasks = (await db.execute(
        select(Task)
        .where(or_(Task.title.ilike(pattern), Task.description.ilike(pattern)))
        .limit(4)
    )).scalars().all()
    for t in tasks:
        results.append({
            "type": "task", "icon": "fa-square-check",
            "title": t.title,
            "subtitle": f"{t.status} · {t.priority} priority",
            "url": "/tasks",
            "color": "var(--yellow)",
        })

    # Knowledge
    chunks = (await db.execute(
        select(KnowledgeChunk)
        .where(or_(KnowledgeChunk.content.ilike(pattern), KnowledgeChunk.summary.ilike(pattern)))
        .limit(4)
    )).scalars().all()
    for c in chunks:
        results.append({
            "type": "knowledge", "icon": "fa-brain",
            "title": (c.summary or c.content or "")[:80],
            "subtitle": c.department or "General",
            "url": "/knowledge-base",
            "color": "var(--accent)",
        })

    return JSONResponse({"results": results, "query": q, "total": len(results)})

@router.get("/platform/audit/export")
async def export_audit(
    format: str = "csv",
    days: int = 90,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in (UserRole.super_admin, UserRole.admin):
        raise HTTPException(status_code=403)

    since = datetime.utcnow() - timedelta(days=days)
    logs = (await db.execute(
        select(AuditLog, User.full_name, User.email)
        .join(User, AuditLog.user_id == User.id)
        .where(AuditLog.created_at >= since)
        .order_by(AuditLog.created_at.desc())
        .limit(10000)
    )).all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Timestamp", "User", "Email", "Action", "Resource Type", "Resource ID", "IP Address", "Details"])
        for log, name, email in logs:
            writer.writerow([
                log.created_at.isoformat() if log.created_at else "",
                name, email, log.action,
                log.resource_type or "", log.resource_id or "",
                log.ip_address or "",
                str(log.details or ""),
            ])
        content = output.getvalue()
        filename = f"audit_log_{datetime.utcnow().strftime('%Y%m%d')}.csv"
        return StreamingResponse(
            iter([content]), media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    elif format == "pdf":
        pdf_bytes = _build_audit_pdf(logs, days)
        filename = f"audit_log_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
        return StreamingResponse(
            io.BytesIO(pdf_bytes), media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    return JSONResponse({"error": "format must be csv or pdf"}, status_code=400)


def _build_audit_pdf(logs, days: int) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"BOSS System — Audit Log Export (Last {days} days)", styles["Title"]))
    story.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%B %d, %Y %H:%M UTC')} · {len(logs)} records", styles["Normal"]))
    story.append(Spacer(1, 12))

    data = [["Timestamp", "User", "Action", "Resource", "IP"]]
    for log, name, email in logs[:500]:
        data.append([
            log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else "",
            f"{name[:20]}",
            log.action[:30] if log.action else "",
            f"{log.resource_type or ''} #{log.resource_id or ''}",
            log.ip_address or "",
        ])

    col_widths = [4*cm, 5*cm, 6*cm, 5*cm, 4*cm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#18181b")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 7.5),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#f8fafc"), colors.white]),
        ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#e5e7eb")),
        ("PADDING",    (0,0), (-1,-1), 4),
    ]))
    story.append(table)

    if len(logs) > 500:
        story.append(Spacer(1,8))
        story.append(Paragraph(f"Showing first 500 of {len(logs)} records. Download CSV for full export.", styles["Normal"]))

    doc.build(story)
    return buf.getvalue()

@router.get("/tenants", response_class=HTMLResponse)
async def tenants_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403)
    tenants = (await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))).scalars().all()
    tenants_data = [
        {
            "id": t.id,
            "name": t.name,
            "slug": t.slug,
            "plan": t.plan,
            "is_active": t.is_active,
            "max_users": t.max_users,
            "domain": t.domain,
            "brand_name": t.brand_name,
            "brand_logo_url": t.brand_logo_url,
            "primary_color": t.primary_color,
            "sidebar_color": t.sidebar_color,
            "created_at": t.created_at,
            "expires_at": t.expires_at,
        }
        for t in tenants
    ]
    return templates.TemplateResponse(request=request, name="platform/tenants.html", context={
        "user": current_user, "page": "platform", "tenants": tenants_data,
    })


@router.post("/tenants/create")
async def create_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403)
    body = await request.json()
    slug = body.get("slug","").strip().lower().replace(" ","-")
    existing = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if existing:
        return JSONResponse({"error": "Slug already exists"}, status_code=400)
    tenant = Tenant(
        name=body.get("name",""),
        slug=slug,
        plan=body.get("plan","starter"),
        max_users=int(body.get("max_users", 10)),
        brand_name=body.get("brand_name",""),
        primary_color=body.get("primary_color","#dc2626"),
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    return JSONResponse({"status":"created","id":tenant.id})


@router.post("/tenants/{tenant_id}/update")
async def update_tenant(
    tenant_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403)
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant: raise HTTPException(404)
    body = await request.json()
    for field in ["name","brand_name","brand_logo_url","primary_color",
                  "sidebar_color","custom_css","plan","max_users","domain"]:
        if field in body:
            setattr(tenant, field, body[field])
    await db.commit()
    return JSONResponse({"status":"updated"})


@router.post("/tenants/{tenant_id}/toggle")
async def toggle_tenant(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403)
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if not tenant: raise HTTPException(404)
    tenant.is_active = not tenant.is_active
    await db.commit()
    return JSONResponse({"is_active": tenant.is_active})