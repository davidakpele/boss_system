from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import (
    User, UserRole, AuditLog, OnboardingStep, OnboardingProgress,
    ComplianceRecord, RiskItem, Document
)
from app.auth import require_user, get_password_hash
import random

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="app/templates")

AVATAR_COLORS = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
    "#10b981", "#3b82f6", "#ef4444", "#14b8a6",
]


# ─────────────── USERS ───────────────

@router.get("/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin", "manager"):
        raise HTTPException(status_code=403)

    users = (await db.execute(select(User).order_by(User.full_name))).scalars().all()
    return templates.TemplateResponse(
        request=request,
        name="users/index.html",
        context={
            "user": current_user,
            "users": users,
            "page": "users",
            "roles": [r.value for r in UserRole],
        }
    )


@router.post("/users/create")
async def create_user(
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    department: str = Form(...),
    role: str = Form("staff"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)

    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        return JSONResponse({"error": "Email already exists"}, status_code=400)

    db.add(User(
        full_name=full_name, email=email,
        hashed_password=get_password_hash(password),
        department=department, role=UserRole(role),
        avatar_color=random.choice(AVATAR_COLORS),
        onboarding_complete=(role in ("super_admin", "admin")),
    ))
    await db.commit()
    return JSONResponse({"status": "created"})


@router.post("/users/{user_id}/toggle")
async def toggle_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user:
        user.is_active = not user.is_active
        await db.commit()
    return JSONResponse({"is_active": user.is_active if user else False})


# ─────────────── ONBOARDING ───────────────

@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    steps = (await db.execute(
        select(OnboardingStep).order_by(OnboardingStep.step_order)
    )).scalars().all()

    new_employees = []
    if current_user.role in ("super_admin", "admin", "manager"):
        for emp in (await db.execute(select(User).where(User.role == UserRole.new_employee))).scalars().all():
            completed = (await db.execute(
                select(func.count(OnboardingProgress.id))
                .where(OnboardingProgress.user_id == emp.id, OnboardingProgress.completed == True)
            )).scalar()
            new_employees.append({
                "user": emp, "completed": completed,
                "total": len(steps),
                "pct": round(completed / len(steps) * 100) if steps else 0,
            })

    my_progress = {}
    for step in steps:
        prog = (await db.execute(
            select(OnboardingProgress).where(
                OnboardingProgress.user_id == current_user.id,
                OnboardingProgress.step_id == step.id,
            )
        )).scalar_one_or_none()
        my_progress[step.id] = prog.completed if prog else False

    return templates.TemplateResponse(
        request=request,
        name="onboarding/index.html",
        context={
            "user": current_user,
            "steps": steps,
            "new_employees": new_employees,
            "my_progress": my_progress,
            "page": "onboarding",
        }
    )


@router.post("/onboarding/step/create")
async def create_step(
    title: str = Form(...),
    description: str = Form(""),
    step_order: int = Form(0),
    is_required: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)
    db.add(OnboardingStep(title=title, description=description, step_order=step_order, is_required=is_required))
    await db.commit()
    return JSONResponse({"status": "created"})


@router.post("/onboarding/step/{step_id}/complete")
async def complete_step(
    step_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from datetime import datetime
    prog = (await db.execute(
        select(OnboardingProgress).where(
            OnboardingProgress.user_id == current_user.id,
            OnboardingProgress.step_id == step_id,
        )
    )).scalar_one_or_none()

    if not prog:
        prog = OnboardingProgress(user_id=current_user.id, step_id=step_id)
        db.add(prog)

    prog.completed = True
    prog.completed_at = datetime.utcnow()

    required_steps = (await db.execute(
        select(OnboardingStep).where(OnboardingStep.is_required == True)
    )).scalars().all()

    all_done = True
    for step in required_steps:
        p = (await db.execute(
            select(OnboardingProgress).where(
                OnboardingProgress.user_id == current_user.id,
                OnboardingProgress.step_id == step.id,
                OnboardingProgress.completed == True,
            )
        )).scalar_one_or_none()
        if not p:
            all_done = False
            break

    if all_done:
        current_user.onboarding_complete = True

    await db.commit()
    return JSONResponse({"completed": True, "onboarding_complete": all_done})


# ─────────────── COMPLIANCE ───────────────

@router.get("/compliance", response_class=HTMLResponse)
async def compliance_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    records = (await db.execute(
        select(ComplianceRecord, Document.title)
        .join(Document, ComplianceRecord.document_id == Document.id)
        .order_by(ComplianceRecord.created_at.desc())
    )).all()

    total = len(records)
    compliant = sum(1 for r, _ in records if r.status == "compliant")
    score = round(compliant / total * 100) if total > 0 else 0
    by_risk = {
        "critical": sum(1 for r, _ in records if r.risk_level == "critical"),
        "high": sum(1 for r, _ in records if r.risk_level == "high"),
        "medium": sum(1 for r, _ in records if r.risk_level == "medium"),
        "low": sum(1 for r, _ in records if r.risk_level == "low"),
    }

    return templates.TemplateResponse(
        request=request,
        name="compliance/index.html",
        context={
            "user": current_user,
            "records": records,
            "score": score,
            "total": total,
            "compliant": compliant,
            "by_risk": by_risk,
            "page": "compliance",
        }
    )


@router.post("/compliance/{record_id}/update")
async def update_compliance_status(
    record_id: int,
    status: str = Form(...),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    record = (await db.execute(
        select(ComplianceRecord).where(ComplianceRecord.id == record_id)
    )).scalar_one_or_none()
    if record:
        record.status = status
        record.notes = notes
        await db.commit()
    return JSONResponse({"status": "updated"})


# ─────────────── RISK MANAGEMENT ───────────────

@router.get("/risk-management", response_class=HTMLResponse)
async def risk_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    risks = (await db.execute(
        select(RiskItem).order_by(RiskItem.risk_score.desc())
    )).scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="risk/index.html",
        context={"user": current_user, "risks": risks, "page": "risk_management"}
    )


@router.post("/risk-management/create")
async def create_risk(
    title: str = Form(...),
    description: str = Form(""),
    category: str = Form("Operational"),
    likelihood: int = Form(3),
    impact: int = Form(3),
    mitigation_plan: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    db.add(RiskItem(
        title=title, description=description, category=category,
        likelihood=likelihood, impact=impact,
        risk_score=float(likelihood * impact),
        mitigation_plan=mitigation_plan, owner_id=current_user.id,
    ))
    await db.commit()
    return JSONResponse({"status": "created"})


# ─────────────── AUDIT LOGS ───────────────

@router.get("/audit-logs", response_class=HTMLResponse)
async def audit_logs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403)

    logs = (await db.execute(
        select(AuditLog, User.full_name)
        .join(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.created_at.desc())
        .limit(100)
    )).all()

    return templates.TemplateResponse(
        request=request,
        name="audit/index.html",
        context={"user": current_user, "logs": logs, "page": "audit"}
    )


# ─────────────── SETTINGS ───────────────

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    return templates.TemplateResponse(
        request=request,
        name="settings/index.html",
        context={"user": current_user, "page": "settings"}
    )


@router.post("/settings/profile")
async def update_profile(
    full_name: str = Form(...),
    department: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    current_user.full_name = full_name
    current_user.department = department
    await db.commit()
    return JSONResponse({"status": "updated"})


@router.post("/settings/password")
async def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.auth import verify_password
    if not verify_password(current_password, current_user.hashed_password):
        return JSONResponse({"error": "Current password incorrect"}, status_code=400)
    current_user.hashed_password = get_password_hash(new_password)
    await db.commit()
    return JSONResponse({"status": "updated"})