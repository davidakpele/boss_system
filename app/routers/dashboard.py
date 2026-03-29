from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import User, Document, DocStatus, ComplianceRecord, AuditLog
from app.auth import require_user
from app.services.websocket_manager import manager

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def root(current_user=Depends(require_user)):
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user),
):
    doc_count = (await db.execute(select(func.count(Document.id)))).scalar()
    user_count = (await db.execute(select(func.count(User.id)))).scalar()
    active_users = (await db.execute(
        select(func.count(User.id)).where(User.is_online == True)
    )).scalar()
    pending_docs = (await db.execute(
        select(func.count(Document.id)).where(Document.status == DocStatus.pending)
    )).scalar()

    total_compliance = (await db.execute(select(func.count(ComplianceRecord.id)))).scalar()
    compliant = (await db.execute(
        select(func.count(ComplianceRecord.id)).where(ComplianceRecord.status == "compliant")
    )).scalar()
    compliance_score = round((compliant / total_compliance * 100) if total_compliance > 0 else 0, 1)

    recent_logs = (await db.execute(
        select(AuditLog, User.full_name)
        .join(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.created_at.desc())
        .limit(8)
    )).all()

    recent_docs = (await db.execute(
        select(Document).order_by(Document.created_at.desc()).limit(5)
    )).scalars().all()

    online_ids = manager.get_all_online_user_ids()

    return templates.TemplateResponse(
        request=request,
        name="dashboard/index.html",
        context={
            "user": current_user,
            "stats": {
                "documents": doc_count,
                "users": user_count,
                "active_users": active_users or len(online_ids),
                "pending_approvals": pending_docs,
                "compliance_score": compliance_score,
            },
            "recent_logs": recent_logs,
            "recent_docs": recent_docs,
            "page": "dashboard",
        }
    )