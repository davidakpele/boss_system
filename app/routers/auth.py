from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Response, status, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.config import settings
from app.database import get_db
from app.models import User, UserRole, AuditLog
import random

# ── Password helpers ──
def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

# ── JWT helpers ──
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

# ── Dependency helpers ──
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    access_token: Optional[str] = Cookie(default=None),
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[User]:
    tok = access_token or token
    if not tok:
        return None
    try:
        payload = jwt.decode(tok, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: int = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

async def require_user(current_user: Optional[User] = Depends(get_current_user)) -> User:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/auth/login"},
        )
    return current_user

async def require_admin(current_user: User = Depends(require_user)) -> User:
    if current_user.role not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# ── Router ──
router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

AVATAR_COLORS = ["#6366f1","#8b5cf6","#ec4899","#f59e0b","#10b981","#3b82f6","#ef4444","#14b8a6"]


@router.get("/ws-token")
async def get_ws_token(
    access_token: Optional[str] = Cookie(default=None),
):
    """
    Returns the JWT token so JavaScript can use it for WebSocket auth.
    The access_token cookie is httpOnly (JS can't read it directly),
    so this endpoint bridges the gap securely — it only returns the
    token if the cookie is already valid.
    """
    if not access_token:
        return JSONResponse({"token": None}, status_code=401)
    # Verify it's still valid before handing it to JS
    try:
        jwt.decode(access_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return JSONResponse({"token": None}, status_code=401)
    return JSONResponse({"token": access_token})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user=Depends(get_current_user)):
    if current_user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request=request, name="auth/login.html", context={})


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request, name="auth/login.html",
            context={"error": "Invalid email or password"}, status_code=401,
        )
    if not user.is_active:
        return templates.TemplateResponse(
            request=request, name="auth/login.html",
            context={"error": "Account deactivated. Contact admin."}, status_code=401,
        )

    user.is_online = True
    token = create_access_token({"sub": str(user.id)})
    db.add(AuditLog(
        user_id=user.id, action="login", resource_type="auth",
        details={"email": email},
        ip_address=request.client.host if request.client else "",
    ))
    await db.commit()

    redirect = RedirectResponse("/dashboard", status_code=302)
    redirect.set_cookie(
        key="access_token", value=token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
    )
    return redirect


@router.get("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user:
        current_user.is_online = False
        await db.commit()
    resp = RedirectResponse("/auth/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="auth/register.html", context={})


@router.post("/register")
async def register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    department: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    count = (await db.execute(select(func.count(User.id)))).scalar()
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        return templates.TemplateResponse(
            request=request, name="auth/register.html",
            context={"error": "Email already registered"}, status_code=400,
        )

    role = UserRole.super_admin if count == 0 else UserRole.new_employee
    user = User(
        full_name=full_name, email=email,
        hashed_password=get_password_hash(password),
        department=department, role=role,
        avatar_color=random.choice(AVATAR_COLORS),
        onboarding_complete=(role == UserRole.super_admin),
    )
    db.add(user)
    await db.commit()
    return RedirectResponse("/auth/login?registered=1", status_code=302)