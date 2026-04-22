"""
app/routers/audit.py
──────────────────────────────────────────────────────────────────────────────
SOC-2 compliant audit log router.

  GET  /audit                  — Audit dashboard page
  GET  /audit/data             — JSON: paginated, filtered audit entries
  GET  /audit/export           — CSV or PDF export
  GET  /audit/stats            — JSON: summary stats (counts by action category)
"""

import csv
import io
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.database import get_db
from app.models import User, UserRole
from app.models import ImmutableAuditLog
from app.auth import require_user
from app.permissions import require_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["audit"])
templates = Jinja2Templates(directory="app/templates")


def _scope_to_tenant(user: User, stmt):
    """Scope audit query to user's tenant (admins see their tenant; super_admin sees all)."""
    if user.role == UserRole.super_admin:
        return stmt
    if user.tenant_id:
        return stmt.where(ImmutableAuditLog.tenant_id == user.tenant_id)
    return stmt


# ── Dashboard Page ────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("audit:read")),
):
    return templates.TemplateResponse(
        request=request,
        name="audit/index.html",
        context={"user": current_user, "page": "audit"},
    )


# ── JSON Data Endpoint ────────────────────────────────────────────────────────

@router.get("/data")
async def audit_data(
    db:            AsyncSession = Depends(get_db),
    current_user:  User         = Depends(require_permission("audit:read")),
    days:          int          = Query(30, ge=1, le=365),
    limit:         int          = Query(100, ge=1, le=500),
    offset:        int          = Query(0, ge=0),
    action:        str          = Query(None),
    resource_type: str          = Query(None),
    user_id:       int          = Query(None),
    status:        str          = Query(None),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    clauses = [ImmutableAuditLog.created_at >= since]

    if action:
        clauses.append(ImmutableAuditLog.action.ilike(f"{action}%"))
    if resource_type:
        clauses.append(ImmutableAuditLog.resource_type == resource_type)
    if user_id:
        clauses.append(ImmutableAuditLog.user_id == user_id)
    if status:
        clauses.append(ImmutableAuditLog.status == status)

    stmt = (
        select(ImmutableAuditLog)
        .where(and_(*clauses))
        .order_by(ImmutableAuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    stmt = _scope_to_tenant(current_user, stmt)

    logs = (await db.execute(stmt)).scalars().all()

    # Total count for pagination
    count_stmt = select(func.count(ImmutableAuditLog.id)).where(and_(*clauses))
    count_stmt = _scope_to_tenant(current_user, count_stmt)
    total = (await db.execute(count_stmt)).scalar() or 0

    return JSONResponse({
        "total":  total,
        "offset": offset,
        "limit":  limit,
        "logs": [
            {
                "id":            l.id,
                "action":        l.action,
                "resource_type": l.resource_type,
                "resource_id":   l.resource_id,
                "resource_name": l.resource_name,
                "user_id":       l.user_id,
                "user_email":    l.user_email,
                "user_role":     l.user_role,
                "status":        l.status,
                "error_msg":     l.error_msg,
                "ip_address":    l.ip_address,
                "details":       l.details or {},
                "created_at":    l.created_at.isoformat() if l.created_at else "",
            }
            for l in logs
        ],
    })


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def audit_stats(
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(require_permission("audit:read")),
    days:         int          = Query(30, ge=1, le=365),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Counts per action prefix (auth, document, user, etc.)
    stmt = (
        select(ImmutableAuditLog.action, func.count(ImmutableAuditLog.id).label("n"))
        .where(ImmutableAuditLog.created_at >= since)
        .group_by(ImmutableAuditLog.action)
        .order_by(func.count(ImmutableAuditLog.id).desc())
        .limit(30)
    )
    stmt = _scope_to_tenant(current_user, stmt)
    rows = (await db.execute(stmt)).all()

    # Counts per unique user
    user_stmt = (
        select(
            ImmutableAuditLog.user_email,
            func.count(ImmutableAuditLog.id).label("n"),
        )
        .where(ImmutableAuditLog.created_at >= since)
        .group_by(ImmutableAuditLog.user_email)
        .order_by(func.count(ImmutableAuditLog.id).desc())
        .limit(10)
    )
    user_stmt = _scope_to_tenant(current_user, user_stmt)
    user_rows = (await db.execute(user_stmt)).all()

    # Failures
    fail_stmt = (
        select(func.count(ImmutableAuditLog.id))
        .where(
            ImmutableAuditLog.created_at >= since,
            ImmutableAuditLog.status == "failure",
        )
    )
    fail_stmt = _scope_to_tenant(current_user, fail_stmt)
    failures = (await db.execute(fail_stmt)).scalar() or 0

    return JSONResponse({
        "days":       days,
        "failures":   failures,
        "by_action":  [{"action": r.action, "count": r.n} for r in rows],
        "top_users":  [{"email": r.user_email or "system", "count": r.n} for r in user_rows],
    })


# ── Export ────────────────────────────────────────────────────────────────────

@router.get("/export")
async def export_audit(
    db:           AsyncSession = Depends(get_db),
    current_user: User         = Depends(require_permission("audit:export")),
    format:       str          = Query("csv"),
    days:         int          = Query(90, ge=1, le=365),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(ImmutableAuditLog)
        .where(ImmutableAuditLog.created_at >= since)
        .order_by(ImmutableAuditLog.created_at.desc())
        .limit(50_000)
    )
    stmt = _scope_to_tenant(current_user, stmt)
    logs = (await db.execute(stmt)).scalars().all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Timestamp (UTC)", "User Email", "Role",
            "Action", "Resource Type", "Resource ID", "Resource Name",
            "Status", "IP Address", "Details",
        ])
        for l in logs:
            writer.writerow([
                l.created_at.isoformat() if l.created_at else "",
                l.user_email or "",
                l.user_role or "",
                l.action,
                l.resource_type or "",
                l.resource_id or "",
                l.resource_name or "",
                l.status or "",
                l.ip_address or "",
                str(l.details or ""),
            ])
        fname = f"audit_soc2_{datetime.utcnow().strftime('%Y%m%d')}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )

    elif format == "pdf":
        pdf = _build_audit_pdf(logs, days, current_user)
        fname = f"audit_soc2_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
        return StreamingResponse(
            io.BytesIO(pdf),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )

    return JSONResponse({"error": "format must be csv or pdf"}, status_code=400)


def _build_audit_pdf(logs, days: int, user) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"BOSS System — SOC-2 Audit Log (Last {days} days)", styles["Title"]),
        Paragraph(
            f"Exported: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} "
            f"by {user.email}  ·  {len(logs)} records",
            styles["Normal"],
        ),
        Spacer(1, 12),
    ]

    data = [["Timestamp", "User", "Action", "Resource", "Status", "IP"]]
    for l in logs[:1000]:
        data.append([
            l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else "",
            (l.user_email or "")[:30],
            l.action[:35] if l.action else "",
            f"{l.resource_type or ''}#{l.resource_id or ''}",
            l.status or "",
            l.ip_address or "",
        ])

    table = Table(data, colWidths=[3.8*cm, 5.5*cm, 5.5*cm, 4*cm, 2.5*cm, 3*cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#18181b")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ("GRID",       (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ("PADDING",    (0, 0), (-1, -1), 4),
    ]))
    story.append(table)

    if len(logs) > 1000:
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            f"Showing first 1,000 of {len(logs)} records. Download CSV for full export.",
            styles["Normal"],
        ))

    doc.build(story)
    return buf.getvalue()