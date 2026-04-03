# src/app/routers/auth.py
from datetime import datetime, timedelta
from typing import Optional
import secrets
import hashlib
import base64
import random
from urllib.parse import urlencode
from app.models import UserRole
import bcrypt
import httpx
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

def require_role(roles: list[str]):
    async def _check(current_user: User = Depends(require_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return _check

# ── Router ──
router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

AVATAR_COLORS = ["#6366f1","#8b5cf6","#ec4899","#f59e0b","#10b981","#3b82f6","#ef4444","#14b8a6"]


# ════════════════════════════════════════════════════════════════
#  SSO — OAuth2 PKCE helpers
# ════════════════════════════════════════════════════════════════

# Provider URLs
GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

MS_TENANT           = getattr(settings, "MS_TENANT", "common")
MS_AUTH_URL         = f"https://login.microsoftonline.com/{MS_TENANT}/oauth2/v2.0/authorize"
MS_TOKEN_URL        = f"https://login.microsoftonline.com/{MS_TENANT}/oauth2/v2.0/token"
MS_USERINFO_URL     = "https://graph.microsoft.com/v1.0/me"

# Domain allowlist: comma-separated in settings, e.g. "acme.com,subsidiary.com"
_raw_domains: str = getattr(settings, "SSO_ALLOWED_DOMAINS", "")
SSO_ALLOWED_DOMAINS: list[str] = (
    [d.strip().lower() for d in _raw_domains.split(",") if d.strip()]
    if _raw_domains else []
)

def _pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge)."""
    verifier  = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _set_sso_cookie(response: RedirectResponse, state: str, verifier: str, provider: str):
    response.set_cookie(
        key="_sso", value=f"{state}:{verifier}:{provider}",
        httponly=True, samesite="lax", max_age=600,
    )

def _get_sso_cookie(request: Request) -> tuple[str, str, str] | None:
    raw = request.cookies.get("_sso")
    if not raw:
        return None
    parts = raw.split(":", 2)
    return tuple(parts) if len(parts) == 3 else None


def _domain_allowed(email: str) -> bool:
    if not SSO_ALLOWED_DOMAINS:
        return True
    return email.split("@")[-1].lower() in SSO_ALLOWED_DOMAINS


async def _sso_callback(
    request: Request,
    db: AsyncSession,
    provider: str,
    token_url: str,
    userinfo_url: str,
    client_id: str,
    client_secret: str,
) -> RedirectResponse:
    """Shared callback: exchange code → fetch profile → upsert user → issue JWT."""
    code           = request.query_params.get("code")
    returned_state = request.query_params.get("state")
    stored         = _get_sso_cookie(request)

    if not stored or stored[0] != returned_state or stored[2] != provider:
        raise HTTPException(400, "Invalid OAuth state — possible CSRF.")

    _, verifier, _ = stored
    redirect_uri   = str(request.base_url).rstrip("/") + f"/auth/sso/{provider}/callback"

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        tr = await client.post(
            token_url,
            data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  redirect_uri,
                "client_id":     client_id,
                "client_secret": client_secret,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
        )
        if tr.status_code != 200:
            raise HTTPException(502, f"Token exchange failed: {tr.text}")

        access_token = tr.json().get("access_token")

        # Fetch user profile from IdP
        ur = await client.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if ur.status_code != 200:
            raise HTTPException(502, "Failed to fetch profile from identity provider.")
        profile = ur.json()

    # Normalise fields across providers
    if provider == "google":
        email     = profile.get("email", "").lower()
        full_name = profile.get("name", email.split("@")[0])
    else:  # microsoft
        email     = (profile.get("mail") or profile.get("userPrincipalName", "")).lower()
        full_name = profile.get("displayName", email.split("@")[0])

    if not email:
        raise HTTPException(400, "Identity provider did not return an email address.")

    if not _domain_allowed(email):
        allowed = ", ".join(SSO_ALLOWED_DOMAINS)
        raise HTTPException(403, f"Email domain not authorised. Allowed domains: {allowed}")

    # Upsert user
    result = await db.execute(select(User).where(User.email == email))
    user   = result.scalar_one_or_none()

    if user is None:
        count = (await db.execute(select(func.count(User.id)))).scalar()
        role  = UserRole.super_admin if count == 0 else UserRole.new_employee
        user  = User(
            email=email,
            full_name=full_name,
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            department="General",
            role=role,
            is_active=True,
            avatar_color=random.choice(AVATAR_COLORS),
            onboarding_complete=(role == UserRole.super_admin),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif not user.is_active:
        raise HTTPException(403, "Your account has been deactivated. Contact your administrator.")
    else:
        # Sync name if it changed in the IdP
        if user.full_name != full_name:
            user.full_name = full_name

    user.is_online = True
    db.add(AuditLog(
        user_id=user.id, action="sso_login", resource_type="auth",
        details={"provider": provider, "email": email},
        ip_address=request.client.host if request.client else "",
    ))
    await db.commit()

    # Issue BOSS JWT — same shape as password login: sub = str(user.id)
    token = create_access_token({"sub": str(user.id)})

    redir = RedirectResponse("/dashboard", status_code=302)
    redir.set_cookie(
        key="access_token", value=token,
        httponly=True, samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    redir.delete_cookie("_sso")
    return redir


# ════════════════════════════════════════════════════════════════
#  SSO routes
# ════════════════════════════════════════════════════════════════

@router.get("/sso/google")
async def sso_google_start(request: Request):
    client_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(503, "Google SSO is not configured on this server.")

    state, (verifier, challenge) = secrets.token_urlsafe(32), _pkce_pair()
    redirect_uri = str(request.base_url).rstrip("/") + "/auth/sso/google/callback"

    params = {
        "client_id":             client_id,
        "redirect_uri":          redirect_uri,
        "response_type":         "code",
        "scope":                 "openid email profile",
        "state":                 state,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
        "access_type":           "offline",
        "prompt":                "select_account",
    }
    redir = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")
    _set_sso_cookie(redir, state, verifier, "google")
    return redir


@router.get("/sso/google/callback")
async def sso_google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    return await _sso_callback(
        request, db,
        provider="google",
        token_url=GOOGLE_TOKEN_URL,
        userinfo_url=GOOGLE_USERINFO_URL,
        client_id=getattr(settings, "GOOGLE_CLIENT_ID", ""),
        client_secret=getattr(settings, "GOOGLE_CLIENT_SECRET", ""),
    )


@router.get("/sso/microsoft")
async def sso_microsoft_start(request: Request):
    client_id = getattr(settings, "MS_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(503, "Microsoft SSO is not configured on this server.")

    state, (verifier, challenge) = secrets.token_urlsafe(32), _pkce_pair()
    redirect_uri = str(request.base_url).rstrip("/") + "/auth/sso/microsoft/callback"

    params = {
        "client_id":             client_id,
        "redirect_uri":          redirect_uri,
        "response_type":         "code",
        "scope":                 "openid email profile User.Read",
        "state":                 state,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
        "response_mode":         "query",
    }
    redir = RedirectResponse(f"{MS_AUTH_URL}?{urlencode(params)}")
    _set_sso_cookie(redir, state, verifier, "microsoft")
    return redir


@router.get("/sso/microsoft/callback")
async def sso_microsoft_callback(request: Request, db: AsyncSession = Depends(get_db)):
    return await _sso_callback(
        request, db,
        provider="microsoft",
        token_url=MS_TOKEN_URL,
        userinfo_url=MS_USERINFO_URL,
        client_id=getattr(settings, "MS_CLIENT_ID", ""),
        client_secret=getattr(settings, "MS_CLIENT_SECRET", ""),
    )


# ════════════════════════════════════════════════════════════════
#  Original routes (unchanged)
# ════════════════════════════════════════════════════════════════

@router.get("/ws-token")
async def get_ws_token(access_token: Optional[str] = Cookie(default=None)):
    if not access_token:
        return JSONResponse({"token": None}, status_code=401)
    try:
        jwt.decode(access_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return JSONResponse({"token": None}, status_code=401)
    return JSONResponse({"token": access_token})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user=Depends(get_current_user)):
    if current_user:
        return RedirectResponse("/dashboard", status_code=302)
    google_enabled    = bool(getattr(settings, "GOOGLE_CLIENT_ID", ""))
    microsoft_enabled = bool(getattr(settings, "MS_CLIENT_ID", ""))
    return templates.TemplateResponse(
        request=request, name="auth/login.html",
        context={
            "google_sso_enabled":    google_enabled,
            "microsoft_sso_enabled": microsoft_enabled,
        },
    )


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
            context={
                "error": "Invalid email or password",
                "google_sso_enabled":    bool(getattr(settings, "GOOGLE_CLIENT_ID", "")),
                "microsoft_sso_enabled": bool(getattr(settings, "MS_CLIENT_ID", "")),
            },
            status_code=401,
        )
    if not user.is_active:
        return templates.TemplateResponse(
            request=request, name="auth/login.html",
            context={
                "error": "Account deactivated. Contact admin.",
                "google_sso_enabled":    bool(getattr(settings, "GOOGLE_CLIENT_ID", "")),
                "microsoft_sso_enabled": bool(getattr(settings, "MS_CLIENT_ID", "")),
            },
            status_code=401,
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
    count    = (await db.execute(select(func.count(User.id)))).scalar()
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