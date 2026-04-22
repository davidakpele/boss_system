# app/routers/auth.py
"""
Authentication router — enterprise-security edition.

Works with your existing app structure (config.settings, database.get_db,
app.models.User / AuditLog).  Every new feature reads from settings directly.

New vs original:
  • Login lockout via LockoutService
  • Login-attempt recording
  • Session creation / listing / revocation
  • 2FA TOTP — setup, enable, verify, disable + backup codes
  • Password-policy enforcement on register & change-password
  • Password-history check (no reuse of last N passwords)
  • API-key creation, listing, revocation
  • All original SSO (Google / Microsoft PKCE) flows kept intact
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets, hashlib, base64, random
from urllib.parse import urlencode

import bcrypt
import httpx
from jose import JWTError, jwt
from fastapi import (
    APIRouter, Depends, HTTPException, Request,
    Form, status, Cookie,
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.config import settings
from app.database import get_db
from app.models import User, UserRole, AuditLog
from app.security_service import (
    LockoutService, SessionService,
    TwoFactorService, APIKeyService, PasswordPolicy,
)
from app.services.audit_service import AuditService

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire    = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

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


router    = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")

AVATAR_COLORS = ["#6366f1","#8b5cf6","#ec4899","#f59e0b",
                 "#10b981","#3b82f6","#ef4444","#14b8a6"]

GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

MS_AUTH_URL     = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize"
MS_TOKEN_URL    = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token"
MS_USERINFO_URL = "https://graph.microsoft.com/v1.0/me"

_raw_domains: str = getattr(settings, "SSO_ALLOWED_DOMAINS", "")
SSO_ALLOWED_DOMAINS: list[str] = (
    [d.strip().lower() for d in _raw_domains.split(",") if d.strip()]
    if _raw_domains else []
)


def _pkce_pair() -> tuple[str, str]:
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
    return tuple(parts) if len(parts) == 3 else None  # type: ignore[return-value]


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
    code           = request.query_params.get("code")
    returned_state = request.query_params.get("state")
    stored         = _get_sso_cookie(request)

    if not stored or stored[0] != returned_state or stored[2] != provider:
        raise HTTPException(400, "Invalid OAuth state — possible CSRF.")

    _, verifier, _ = stored
    redirect_uri   = str(request.base_url).rstrip("/") + f"/auth/sso/{provider}/callback"

    async with httpx.AsyncClient() as client:
        tr = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": redirect_uri, "client_id": client_id,
                "client_secret": client_secret, "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
        )
        if tr.status_code != 200:
            raise HTTPException(502, f"Token exchange failed: {tr.text}")
        idp_token = tr.json().get("access_token")

        ur = await client.get(userinfo_url, headers={"Authorization": f"Bearer {idp_token}"})
        if ur.status_code != 200:
            raise HTTPException(502, "Failed to fetch profile from identity provider.")
        profile = ur.json()

    if provider == "google":
        email     = profile.get("email", "").lower()
        full_name = profile.get("name", email.split("@")[0])
    else:
        email     = (profile.get("mail") or profile.get("userPrincipalName", "")).lower()
        full_name = profile.get("displayName", email.split("@")[0])

    if not email:
        raise HTTPException(400, "Identity provider did not return an email address.")
    if not _domain_allowed(email):
        raise HTTPException(403, f"Email domain not authorised.")

    result = await db.execute(select(User).where(User.email == email))
    user   = result.scalar_one_or_none()

    if user is None:
        count = (await db.execute(select(func.count(User.id)))).scalar()
        role  = UserRole.super_admin if count == 0 else UserRole.new_employee
        user  = User(
            email=email, full_name=full_name,
            hashed_password=get_password_hash(secrets.token_urlsafe(32)),
            department="General", role=role, is_active=True,
            avatar_color=random.choice(AVATAR_COLORS),
            onboarding_complete=(role == UserRole.super_admin),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif not user.is_active:
        raise HTTPException(403, "Your account has been deactivated.")
    else:
        if user.full_name != full_name:
            user.full_name = full_name

    user.is_online = True
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")

    session = await SessionService.create(db, user.id, ip, ua)
    token   = create_access_token({"sub": str(user.id), "sid": session.id})

    db.add(AuditLog(
        user_id=user.id, action="sso_login", resource_type="auth",
        details={"provider": provider, "email": email}, ip_address=ip,
    ))
    await db.commit()

    redir = RedirectResponse("/dashboard", status_code=302)
    redir.set_cookie(
        key="access_token", value=token,
        httponly=True, samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    redir.delete_cookie("_sso")
    return redir


@router.get("/sso/google")
async def sso_google_start(request: Request):
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google SSO is not configured.")
    state, (verifier, challenge) = secrets.token_urlsafe(32), _pkce_pair()
    redirect_uri = str(request.base_url).rstrip("/") + "/auth/sso/google/callback"
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID, "redirect_uri": redirect_uri,
        "response_type": "code", "scope": "openid email profile",
        "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "access_type": "offline", "prompt": "select_account",
    }
    redir = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")
    _set_sso_cookie(redir, state, verifier, "google")
    return redir


@router.get("/sso/google/callback")
async def sso_google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    return await _sso_callback(
        request, db, provider="google",
        token_url=GOOGLE_TOKEN_URL, userinfo_url=GOOGLE_USERINFO_URL,
        client_id=settings.GOOGLE_CLIENT_ID, client_secret=settings.GOOGLE_CLIENT_SECRET,
    )


@router.get("/sso/microsoft")
async def sso_microsoft_start(request: Request):
    if not settings.MICROSOFT_CLIENT_ID:
        raise HTTPException(503, "Microsoft SSO is not configured.")
    state, (verifier, challenge) = secrets.token_urlsafe(32), _pkce_pair()
    redirect_uri = str(request.base_url).rstrip("/") + "/auth/sso/microsoft/callback"
    params = {
        "client_id": settings.MICROSOFT_CLIENT_ID, "redirect_uri": redirect_uri,
        "response_type": "code", "scope": "openid email profile User.Read",
        "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "response_mode": "query",
    }
    redir = RedirectResponse(f"{MS_AUTH_URL}?{urlencode(params)}")
    _set_sso_cookie(redir, state, verifier, "microsoft")
    return redir


@router.get("/sso/microsoft/callback")
async def sso_microsoft_callback(request: Request, db: AsyncSession = Depends(get_db)):
    return await _sso_callback(
        request, db, provider="microsoft",
        token_url=MS_TOKEN_URL, userinfo_url=MS_USERINFO_URL,
        client_id=settings.MICROSOFT_CLIENT_ID, client_secret=settings.MICROSOFT_CLIENT_SECRET,
    )

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
    return templates.TemplateResponse(
        request=request, name="auth/login.html",
        context={
            "google_sso_enabled":    bool(settings.GOOGLE_CLIENT_ID),
            "microsoft_sso_enabled": bool(settings.MICROSOFT_CLIENT_ID),
        },
    )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")

    def _fail(msg: str, code: int = 401):
        return templates.TemplateResponse(
            request=request, name="auth/login.html",
            context={
                "error": msg,
                "google_sso_enabled":    bool(settings.GOOGLE_CLIENT_ID),
                "microsoft_sso_enabled": bool(settings.MICROSOFT_CLIENT_ID),
            },
            status_code=code,
        )

    locked, unlock_at = await LockoutService.is_locked(db, email)
    if locked:
        unlock_str = unlock_at.strftime("%H:%M UTC") if unlock_at else "later"
        return _fail(
            f"Account temporarily locked after too many failed attempts. "
            f"Try again after {unlock_str}.",
            429,
        )
        
    result = await db.execute(select(User).where(User.email == email))
    user   = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        await LockoutService.record_attempt(db, email, ip, success=False, user_agent=ua)
        return _fail("Invalid email or password.")

    if not user.is_active:
        return _fail("Account deactivated. Contact your administrator.")
    await LockoutService.record_attempt(db, email, ip, success=True, user_agent=ua)
    if await TwoFactorService.is_enabled(db, user.id):
        pending = create_access_token(
            {"sub": str(user.id), "2fa_pending": True},
            expires_delta=timedelta(minutes=5),
        )
        redir = RedirectResponse("/auth/2fa/verify", status_code=302)
        redir.set_cookie("_2fa_pending", pending, httponly=True, samesite="lax", max_age=300)
        return redir

    user.is_online = True
    session = await SessionService.create(db, user.id, ip, ua)
    token   = create_access_token({"sub": str(user.id), "sid": session.id})

    await AuditService.log_auth(db, user, "auth.login", request=request, details={"email": email})

    await db.commit()

    redirect = RedirectResponse("/dashboard", status_code=302)
    redirect.set_cookie(
        key="access_token", value=token,
        httponly=True, samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
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
        try:
            await AuditService.log_auth(db, current_user, "auth.logout", request=request)
            tok = request.cookies.get("access_token")
            if tok:
                payload = jwt.decode(tok, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
                sid = payload.get("sid")
                if sid:
                    await SessionService.revoke(db, int(sid), current_user.id)
        except Exception:
            pass
        await db.commit()

    resp = RedirectResponse("/auth/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="auth/register.html",
        context={"policy_hint": PasswordPolicy.hint()},
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
    violations = PasswordPolicy.validate(password)
    if violations:
        return templates.TemplateResponse(
            request=request, name="auth/register.html",
            context={"error": " ".join(violations), "policy_hint": PasswordPolicy.hint()},
            status_code=400,
        )

    count    = (await db.execute(select(func.count(User.id)))).scalar()
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        return templates.TemplateResponse(
            request=request, name="auth/register.html",
            context={"error": "Email already registered", "policy_hint": PasswordPolicy.hint()},
            status_code=400,
        )

    role   = UserRole.super_admin if count == 0 else UserRole.new_employee
    hashed = get_password_hash(password)

    user = User(
        full_name=full_name, email=email,
        hashed_password=hashed,
        department=department, role=role,
        avatar_color=random.choice(AVATAR_COLORS),
        onboarding_complete=(role == UserRole.super_admin),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await AuditService.log_auth(db, user, "auth.register", request=request, details={"email": email, "department": department})
    await PasswordPolicy.record(db, user.id, hashed)
    await db.commit()

    return RedirectResponse("/auth/login?registered=1", status_code=302)


@router.get("/2fa/setup", response_class=HTMLResponse)
async def twofa_setup_page(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    data = await TwoFactorService.setup(db, current_user)
    return templates.TemplateResponse(
        request=request, name="auth/2fa_setup.html",
        context={"qr_url": data["qr_url"], "secret": data["secret"]},
    )


@router.post("/2fa/setup")
async def twofa_setup_confirm(
    request: Request,
    otp: str = Form(...),
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    success, backup_codes = await TwoFactorService.enable(db, current_user.id, otp)
    if not success:
        data = await TwoFactorService.setup(db, current_user)
        return templates.TemplateResponse(
            request=request, name="auth/2fa_setup.html",
            context={
                "qr_url": data["qr_url"], "secret": data["secret"],
                "error": "Invalid code — please try again.",
            },
            status_code=400,
        )
    return templates.TemplateResponse(
        request=request, name="auth/2fa_backup_codes.html",
        context={"backup_codes": backup_codes},
    )


@router.get("/2fa/verify", response_class=HTMLResponse)
async def twofa_verify_page(request: Request):
    if not request.cookies.get("_2fa_pending"):
        return RedirectResponse("/auth/login", status_code=302)
    return templates.TemplateResponse(request=request, name="auth/2fa_verify.html", context={})


@router.post("/2fa/verify")
async def twofa_verify(
    request: Request,
    otp: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    pending = request.cookies.get("_2fa_pending")
    if not pending:
        return RedirectResponse("/auth/login", status_code=302)

    try:
        payload = jwt.decode(pending, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if not payload.get("2fa_pending"):
            raise ValueError
        user_id = int(payload["sub"])
    except Exception:
        resp = RedirectResponse("/auth/login", status_code=302)
        resp.delete_cookie("_2fa_pending")
        return resp

    if not await TwoFactorService.verify(db, user_id, otp):
        return templates.TemplateResponse(
            request=request, name="auth/2fa_verify.html",
            context={"error": "Invalid code — please try again."},
            status_code=401,
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    ip      = request.client.host if request.client else ""
    ua      = request.headers.get("user-agent", "")
    session = await SessionService.create(db, user.id, ip, ua)
    token   = create_access_token({"sub": str(user.id), "sid": session.id})

    user.is_online = True
    db.add(AuditLog(
        user_id=user.id, action="login_2fa", resource_type="auth",
        details={"ip": ip}, ip_address=ip,
    ))
    await db.commit()

    redir = RedirectResponse("/dashboard", status_code=302)
    redir.set_cookie(
        "access_token", token,
        httponly=True, samesite="lax",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    redir.delete_cookie("_2fa_pending")
    return redir


@router.post("/2fa/disable")
async def twofa_disable(
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await TwoFactorService.disable(db, current_user.id)
    return JSONResponse({"message": "2FA disabled."})


@router.get("/sessions", response_class=HTMLResponse)
async def list_sessions(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    sessions = await SessionService.get_active(db, current_user.id)
    return templates.TemplateResponse(
        request=request, name="auth/sessions.html",
        context={"sessions": sessions},
    )


@router.post("/sessions/{session_id}/revoke")
async def revoke_session(
    session_id: int,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await SessionService.revoke(db, session_id, current_user.id)
    if not ok:
        raise HTTPException(404, "Session not found.")
    return JSONResponse({"message": "Session revoked."})


@router.post("/sessions/revoke-all")
async def revoke_all_sessions(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    current_tok = request.cookies.get("access_token", "")
    count = await SessionService.revoke_all(db, current_user.id, except_token=current_tok)
    return JSONResponse({"message": f"{count} other session(s) revoked."})


@router.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    keys = await APIKeyService.list_for_user(db, current_user.id)
    return templates.TemplateResponse(
        request=request, name="auth/api_keys.html",
        context={"keys": keys},
    )


@router.post("/api-keys")
async def create_api_key(
    name: str = Form(...),
    scopes: str = Form(""),
    expires_in_days: Optional[int] = Form(None),
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    raw, key   = await APIKeyService.create(db, current_user.id, name, scope_list, expires_in_days)
    return JSONResponse({
        "message":  "API key created. Copy it now — it will not be shown again.",
        "raw_key":  raw,
        "key_id":   key.id,
        "prefix":   key.key_prefix,
    })


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await APIKeyService.revoke(db, key_id, current_user.id)
    if not ok:
        raise HTTPException(404, "API key not found.")
    return JSONResponse({"message": "API key revoked."})


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    current_user: User = Depends(require_user),
):
    return templates.TemplateResponse(
        request=request, name="auth/change_password.html",
        context={"policy_hint": PasswordPolicy.hint()},
    )


@router.post("/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    def _err(msg: str):
        return templates.TemplateResponse(
            request=request, name="auth/change_password.html",
            context={"error": msg, "policy_hint": PasswordPolicy.hint()},
            status_code=400,
        )

    if not verify_password(current_password, current_user.hashed_password):
        return _err("Current password is incorrect.")

    if new_password != confirm_password:
        return _err("New passwords do not match.")

    violations = PasswordPolicy.validate(new_password)
    if violations:
        return _err(" ".join(violations))

    if await PasswordPolicy.check_history(db, current_user.id, new_password):
        return _err(
            f"You cannot reuse any of your last {settings.PASSWORD_HISTORY_DEPTH} passwords."
        )

    new_hash                      = get_password_hash(new_password)
    current_user.hashed_password  = new_hash
    await PasswordPolicy.record(db, current_user.id, new_hash)

    db.add(AuditLog(
        user_id=current_user.id, action="password_change", resource_type="auth",
        details={}, ip_address=request.client.host if request.client else "",
    ))
    await db.commit()

    return templates.TemplateResponse(
        request=request, name="auth/change_password.html",
        context={
            "success":     "Password changed successfully.",
            "policy_hint": PasswordPolicy.hint(),
        },
    )