# app/routers/analytics.py
"""
Analytics & Reporting
  GET  /analytics                    — main analytics dashboard (charts)
  GET  /analytics/data/overview      — JSON: headline numbers for charts
  GET  /analytics/data/uploads       — JSON: document uploads over time (30 days)
  GET  /analytics/data/activity      — JSON: user activity heatmap (last 12 weeks)
  GET  /analytics/data/compliance    — JSON: compliance score trend (12 months)
  GET  /analytics/data/knowledge     — JSON: knowledge base growth (30 days)
  GET  /analytics/data/top-users     — JSON: top users by activity

  GET  /analytics/user-activity      — user activity report page (admin)
  GET  /analytics/user-activity/data — JSON: per-user stats

  GET  /analytics/reports            — reports page
  GET  /analytics/reports/department-knowledge  — download PDF
  POST /analytics/reports/generate   — trigger AI report generation
"""
import io
import json
import logging
from datetime import datetime, timedelta, date
from collections import defaultdict

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text

from app.database import get_db
from app.models import (
    User, Document, Message, KnowledgeChunk, ComplianceRecord,
    AuditLog, AIConversation, AIMessage, UserRole
)
from app.auth import require_user
from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])
templates = Jinja2Templates(directory="app/templates")

def _date_range(days: int):
    today = date.today()
    return [today - timedelta(days=i) for i in range(days - 1, -1, -1)]


def _week_range(weeks: int):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return [monday - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]

@router.get("", response_class=HTMLResponse)
async def analytics_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in (UserRole.super_admin, UserRole.admin, UserRole.manager):
        raise HTTPException(status_code=403)

    total_docs   = (await db.execute(select(func.count(Document.id)))).scalar() or 0
    total_users  = (await db.execute(select(func.count(User.id)).where(User.is_active == True))).scalar() or 0
    total_chunks = (await db.execute(select(func.count(KnowledgeChunk.id)))).scalar() or 0
    total_msgs   = (await db.execute(select(func.count(Message.id)).where(Message.is_deleted == False))).scalar() or 0

    comp_total = (await db.execute(select(func.count(ComplianceRecord.id)))).scalar() or 0
    comp_ok    = (await db.execute(
        select(func.count(ComplianceRecord.id))
        .where(ComplianceRecord.status == "compliant")
    )).scalar() or 0
    compliance_pct = round((comp_ok / comp_total * 100) if comp_total else 0, 1)

    departments = (await db.execute(
        select(KnowledgeChunk.department).distinct().where(KnowledgeChunk.department != None)
    )).scalars().all()

    return templates.TemplateResponse(request=request, name="analytics/dashboard.html", context={
        "user": current_user, "page": "analytics",
        "total_docs": total_docs, "total_users": total_users,
        "total_chunks": total_chunks, "total_msgs": total_msgs,
        "compliance_pct": compliance_pct, "departments": departments,
    })

@router.get("/data/uploads")
async def uploads_over_time(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    days: int = 30,
):
    """Document uploads per day for the last `days` days."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(
        select(
            func.date(Document.created_at).label("day"),
            func.count(Document.id).label("count"),
        )
        .where(Document.created_at >= since)
        .group_by(func.date(Document.created_at))
        .order_by(func.date(Document.created_at))
    )).all()

    day_map = {str(r.day): r.count for r in rows}
    labels = [str(d) for d in _date_range(days)]
    values = [day_map.get(lbl, 0) for lbl in labels]

    return JSONResponse({"labels": labels, "values": values})


@router.get("/data/messages")
async def messages_over_time(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    days: int = 30,
):
    """Messages sent per day for the last `days` days."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(
        select(
            func.date(Message.created_at).label("day"),
            func.count(Message.id).label("count"),
        )
        .where(Message.created_at >= since, Message.is_deleted == False)
        .group_by(func.date(Message.created_at))
        .order_by(func.date(Message.created_at))
    )).all()

    day_map = {str(r.day): r.count for r in rows}
    labels = [str(d) for d in _date_range(days)]
    values = [day_map.get(lbl, 0) for lbl in labels]
    return JSONResponse({"labels": labels, "values": values})


@router.get("/data/activity-heatmap")
async def activity_heatmap(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """
    Returns a 7×12 matrix (day-of-week × week) of login counts
    for a GitHub-style contribution heatmap.
    """
    since = datetime.utcnow() - timedelta(weeks=12)
    rows = (await db.execute(
        select(
            func.date(AuditLog.created_at).label("day"),
            func.count(AuditLog.id).label("count"),
        )
        .where(AuditLog.created_at >= since, AuditLog.action.like("login%"))
        .group_by(func.date(AuditLog.created_at))
    )).all()

    day_map = {str(r.day): r.count for r in rows}
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    cells = []
    for w in range(11, -1, -1):
        week_start = monday - timedelta(weeks=w)
        for d in range(7):
            cell_date = week_start + timedelta(days=d)
            cells.append({
                "date": str(cell_date),
                "count": day_map.get(str(cell_date), 0),
                "week": 11 - w,
                "day": d,
            })
    return JSONResponse({"cells": cells})


@router.get("/data/compliance-trend")
async def compliance_trend(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    months: int = 12,
):
    """Compliance score for each of the last N months."""
    labels, values = [], []
    today = date.today()
    for i in range(months - 1, -1, -1):
        # first day of that month
        month_date = (today.replace(day=1) - timedelta(days=1)).replace(day=1) if i == 0 else None
        target = date(today.year, today.month, 1) - timedelta(days=30 * i)
        month_start = target.replace(day=1)
        next_month  = (month_start + timedelta(days=32)).replace(day=1)

        total = (await db.execute(
            select(func.count(ComplianceRecord.id))
            .where(ComplianceRecord.created_at < next_month)
        )).scalar() or 0

        compliant = (await db.execute(
            select(func.count(ComplianceRecord.id))
            .where(
                ComplianceRecord.status == "compliant",
                ComplianceRecord.created_at < next_month,
            )
        )).scalar() or 0

        score = round((compliant / total * 100) if total else 0, 1)
        labels.append(month_start.strftime("%b %Y"))
        values.append(score)

    return JSONResponse({"labels": labels, "values": values})


@router.get("/data/knowledge-growth")
async def knowledge_growth(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    days: int = 30,
):
    """Cumulative knowledge chunks over last N days."""
    since = datetime.utcnow() - timedelta(days=days)
    rows = (await db.execute(
        select(
            func.date(KnowledgeChunk.created_at).label("day"),
            func.count(KnowledgeChunk.id).label("count"),
        )
        .where(KnowledgeChunk.created_at >= since)
        .group_by(func.date(KnowledgeChunk.created_at))
        .order_by(func.date(KnowledgeChunk.created_at))
    )).all()

    day_map = {str(r.day): r.count for r in rows}
    labels = [str(d) for d in _date_range(days)]
    daily = [day_map.get(lbl, 0) for lbl in labels]
    cumulative, running = [], 0
    for v in daily:
        running += v
        cumulative.append(running)

    return JSONResponse({"labels": labels, "daily": daily, "cumulative": cumulative})


@router.get("/data/knowledge-by-dept")
async def knowledge_by_dept(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Knowledge chunks grouped by department (pie/donut)."""
    try:
        from sqlalchemy import case
        dept_expr = case(
            (KnowledgeChunk.department == None, "General"),
            (KnowledgeChunk.department == "",   "General"),
            else_=KnowledgeChunk.department
        ).label("dept")
 
        rows = (await db.execute(
            select(dept_expr, func.count(KnowledgeChunk.id).label("count"))
            .group_by(dept_expr)
            .order_by(func.count(KnowledgeChunk.id).desc())
        )).all()
 
        if not rows:
            return JSONResponse({"labels": ["No data"], "values": [1]})
 
        return JSONResponse({
            "labels": [str(r.dept) for r in rows],
            "values": [int(r.count) for r in rows],
        })
 
    except Exception as e:
        logger.error(f"knowledge-by-dept error: {e}")
        return JSONResponse({"labels": ["No data"], "values": [1]})

@router.get("/data/top-users")
async def top_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Top 10 most active users (message count last 30 days)."""
    since = datetime.utcnow() - timedelta(days=30)
    rows = (await db.execute(
        select(
            User.full_name,
            User.department,
            User.avatar_color,
            func.count(Message.id).label("msg_count"),
        )
        .join(Message, Message.sender_id == User.id)
        .where(Message.created_at >= since, Message.is_deleted == False)
        .group_by(User.id, User.full_name, User.department, User.avatar_color)
        .order_by(func.count(Message.id).desc())
        .limit(10)
    )).all()

    return JSONResponse([
        {"name": r.full_name, "dept": r.department or "—",
         "color": r.avatar_color, "count": r.msg_count}
        for r in rows
    ])

@router.get("/user-activity", response_class=HTMLResponse)
async def user_activity_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in (UserRole.super_admin, UserRole.admin):
        raise HTTPException(status_code=403)
    return templates.TemplateResponse(request=request, name="analytics/user_activity.html", context={
        "user": current_user, "page": "analytics",
    })


@router.get("/user-activity/data")
async def user_activity_data(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    days: int = 30,
):
    if current_user.role not in (UserRole.super_admin, UserRole.admin):
        raise HTTPException(status_code=403)

    since = datetime.utcnow() - timedelta(days=days)
    users = (await db.execute(
        select(User).where(User.is_active == True).order_by(User.full_name)
    )).scalars().all()

    results = []
    for u in users:
        msg_count = (await db.execute(
            select(func.count(Message.id))
            .where(Message.sender_id == u.id, Message.created_at >= since,
                   Message.is_deleted == False)
        )).scalar() or 0

        doc_count = (await db.execute(
            select(func.count(Document.id))
            .where(Document.author_id == u.id, Document.created_at >= since)
        )).scalar() or 0

        ai_count = (await db.execute(
            select(func.count(AIConversation.id))
            .where(AIConversation.user_id == u.id, AIConversation.created_at >= since)
        )).scalar() or 0

        login_count = (await db.execute(
            select(func.count(AuditLog.id))
            .where(AuditLog.user_id == u.id, AuditLog.action.like("login%"),
                   AuditLog.created_at >= since)
        )).scalar() or 0

        # Last seen
        last_log = (await db.execute(
            select(AuditLog.created_at)
            .where(AuditLog.user_id == u.id)
            .order_by(AuditLog.created_at.desc()).limit(1)
        )).scalar()

        results.append({
            "id": u.id,
            "name": u.full_name,
            "email": u.email,
            "dept": u.department or "—",
            "role": u.role.value,
            "color": u.avatar_color,
            "is_online": u.is_online,
            "messages": msg_count,
            "documents": doc_count,
            "ai_queries": ai_count,
            "logins": login_count,
            "last_seen": last_log.isoformat() if last_log else None,
            "activity_score": msg_count + doc_count * 3 + ai_count * 2 + login_count,
        })

    results.sort(key=lambda x: x["activity_score"], reverse=True)
    return JSONResponse(results)


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in (UserRole.super_admin, UserRole.admin, UserRole.manager):
        raise HTTPException(status_code=403)
    departments = (await db.execute(
        select(KnowledgeChunk.department).distinct().where(KnowledgeChunk.department != None)
    )).scalars().all()
    return templates.TemplateResponse(request=request, name="analytics/reports.html", context={
        "user": current_user, "page": "analytics", "departments": departments,
    })


@router.get("/reports/department-knowledge")
async def download_dept_report(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    department: str = None,
    weeks: int = 4,
):
    """Generate and stream a PDF knowledge report."""
    if current_user.role not in (UserRole.super_admin, UserRole.admin, UserRole.manager):
        raise HTTPException(status_code=403)

    since = datetime.utcnow() - timedelta(weeks=weeks)

    stmt = select(KnowledgeChunk).where(KnowledgeChunk.created_at >= since)
    if department:
        stmt = stmt.where(KnowledgeChunk.department == department)
    stmt = stmt.order_by(KnowledgeChunk.created_at.desc()).limit(100)
    chunks = (await db.execute(stmt)).scalars().all()

    comp_stmt = select(ComplianceRecord)
    if department:
        pass  
    comp_stmt = comp_stmt.order_by(ComplianceRecord.created_at.desc()).limit(30)
    comp_records = (await db.execute(comp_stmt)).scalars().all()

    doc_stmt = select(Document).where(Document.created_at >= since)
    if department:
        doc_stmt = doc_stmt.where(Document.department == department)
    new_docs = (await db.execute(doc_stmt)).scalars().all()

    ai_summary = ""
    if chunks:
        sample = "\n".join(c.summary or c.content[:300] for c in chunks[:10])
        ai_msgs = [
            {"role": "system", "content": (
                "You are a business analyst. Summarise the key business knowledge added "
                "this period based on these knowledge chunks. Write 3-5 bullet points of "
                "the most important insights. Be concise and professional."
            )},
            {"role": "user", "content": f"Knowledge chunks:\n{sample}"},
        ]
        ai_summary = await ai_service.chat_complete(ai_msgs) or "No AI summary available."
    pdf_bytes = _build_pdf(
        department=department or "All Departments",
        weeks=weeks,
        chunks=chunks,
        new_docs=new_docs,
        comp_records=comp_records,
        ai_summary=ai_summary,
        generated_by=current_user.full_name,
    )

    fname = f"knowledge_report_{department or 'all'}_{date.today()}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


def _build_pdf(department, weeks, chunks, new_docs, comp_records, ai_summary, generated_by):
    """Build a styled PDF using ReportLab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"],
                                 fontSize=22, textColor=colors.HexColor("#1e40af"),
                                 spaceAfter=6)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"],
                         fontSize=13, textColor=colors.HexColor("#1e3a5f"),
                         spaceBefore=14, spaceAfter=6)
    h3 = ParagraphStyle("H3", parent=styles["Heading3"],
                         fontSize=11, textColor=colors.HexColor("#374151"),
                         spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("Body", parent=styles["Normal"],
                          fontSize=9.5, leading=14, textColor=colors.HexColor("#374151"))
    small = ParagraphStyle("Small", parent=body,
                           fontSize=8.5, textColor=colors.HexColor("#6b7280"))
    bullet = ParagraphStyle("Bullet", parent=body,
                             leftIndent=12, bulletIndent=0,
                             spaceAfter=3, bulletText="•")

    story = []

    story.append(Paragraph("BOSS System", ParagraphStyle("Brand", parent=styles["Normal"],
                             fontSize=10, textColor=colors.HexColor("#6366f1"), spaceAfter=2)))
    story.append(Paragraph(f"Department Knowledge Report", title_style))
    story.append(Paragraph(f"Department: <b>{department}</b> &nbsp;·&nbsp; Period: Last {weeks} week{'s' if weeks>1 else ''}",
                            ParagraphStyle("Sub", parent=body, textColor=colors.HexColor("#6b7280"))))
    story.append(Paragraph(f"Generated: {date.today().strftime('%B %d, %Y')} &nbsp;·&nbsp; By: {generated_by}", small))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#3b82f6"), spaceAfter=12))

    comp_total = len(comp_records)
    comp_ok = sum(1 for c in comp_records if c.status == "compliant")
    comp_pct = round((comp_ok / comp_total * 100) if comp_total else 0)

    stats_data = [
        ["Metric", "Value"],
        ["New Knowledge Chunks", str(len(chunks))],
        ["New Documents", str(len(new_docs))],
        ["Compliance Records", str(comp_total)],
        ["Compliance Score", f"{comp_pct}%"],
    ]
    stats_table = Table(stats_data, colWidths=[10*cm, 6*cm])
    stats_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTSIZE",   (0, 0), (-1, 0), 10),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
        ("GRID",       (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("PADDING",    (0, 0), (-1, -1), 8),
        ("FONTSIZE",   (0, 1), (-1, -1), 9.5),
    ]))
    story.append(stats_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("AI-Generated Insights", h2))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#93c5fd"), spaceAfter=8))
    for line in ai_summary.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith(("•", "-", "*")):
            story.append(Paragraph(line.lstrip("•-* "), bullet))
        else:
            story.append(Paragraph(line, body))
    story.append(Spacer(1, 14))
    if new_docs:
        story.append(Paragraph(f"New Documents ({len(new_docs)})", h2))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#93c5fd"), spaceAfter=8))
        doc_data = [["Title", "Status", "Access", "Date"]]
        for d in new_docs[:20]:
            doc_data.append([
                d.title[:55] + ("…" if len(d.title) > 55 else ""),
                d.status.value,
                d.access_level.value,
                d.created_at.strftime("%b %d") if d.created_at else "—",
            ])
        doc_table = Table(doc_data, colWidths=[9.5*cm, 2.5*cm, 2.5*cm, 2*cm])
        doc_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 8.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
            ("PADDING",    (0, 0), (-1, -1), 6),
        ]))
        story.append(doc_table)
        story.append(Spacer(1, 14))

    if comp_records:
        story.append(Paragraph("Compliance Status", h2))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#93c5fd"), spaceAfter=8))
        c_data = [["Regulation", "Risk Level", "Status"]]
        for c in comp_records[:15]:
            c_data.append([
                (c.regulation_type or "General")[:40],
                c.risk_level or "medium",
                c.status or "identified",
            ])
        c_table = Table(c_data, colWidths=[10*cm, 3*cm, 3.5*cm])
        c_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 8.5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
            ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
            ("PADDING",    (0, 0), (-1, -1), 6),
        ]))
        story.append(c_table)
        story.append(Spacer(1, 14))

    if chunks:
        story.append(Paragraph(f"Knowledge Added ({len(chunks)} chunks)", h2))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#93c5fd"), spaceAfter=8))
        for i, ch in enumerate(chunks[:15], 1):
            source_label = f"[{ch.source_type}]" if ch.source_type else ""
            preview = (ch.summary or ch.content or "")[:200].replace("\n", " ")
            story.append(KeepTogether([
                Paragraph(f"{i}. {source_label} {preview}…" if len(ch.content or "") > 200 else f"{i}. {source_label} {preview}", body),
                Spacer(1, 4),
            ]))
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#d1d5db")))
    story.append(Paragraph(f"BOSS System — Business Operating System &nbsp;·&nbsp; MindSync AI Consults &nbsp;·&nbsp; {date.today().strftime('%Y')}",
                            ParagraphStyle("Footer", parent=small, alignment=1)))

    doc.build(story)
    return buf.getvalue()