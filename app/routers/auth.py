from fastapi import APIRouter, Depends, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import timedelta
from app.database import get_db
from app.models import User, UserRole, AuditLog
from app.auth import verify_password, get_password_hash, create_access_token, get_current_user
from app.config import settings
import random

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

AVATAR_COLORS = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
    "#10b981", "#3b82f6", "#ef4444", "#14b8a6",
]


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user=Depends(get_current_user)):
    if current_user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={}
    )


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"error": "Invalid email or password"},
            status_code=401,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            context={"error": "Account is deactivated. Contact admin."},
            status_code=401,
        )

    user.is_online = True
    await db.commit()

    token = create_access_token({"sub": str(user.id)})

    log = AuditLog(
        user_id=user.id,
        action="login",
        resource_type="auth",
        details={"email": email},
        ip_address=request.client.host if request.client else "",
    )
    db.add(log)
    await db.commit()

    redirect = RedirectResponse("/dashboard", status_code=302)
    redirect.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
    )
    return redirect


@router.get("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user:
        current_user.is_online = False
        await db.commit()

    response = RedirectResponse("/auth/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="auth/register.html",
        context={}
    )


@router.post("/register")
async def register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    department: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    count_result = await db.execute(select(func.count(User.id)))
    user_count = count_result.scalar()

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(
            request=request,
            name="auth/register.html",
            context={"error": "Email already registered"},
            status_code=400,
        )

    role = UserRole.super_admin if user_count == 0 else UserRole.new_employee
    color = random.choice(AVATAR_COLORS)

    user = User(
        full_name=full_name,
        email=email,
        hashed_password=get_password_hash(password),
        department=department,
        role=role,
        avatar_color=color,
        onboarding_complete=(role == UserRole.super_admin),
    )
    db.add(user)
    await db.commit()

    return RedirectResponse("/auth/login?registered=1", status_code=302)