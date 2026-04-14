# app/routers/sso.py
"""
OAuth2 SSO — Google Workspace & Microsoft 365
Routes:
  GET  /auth/sso/google              → redirect to Google consent
  GET  /auth/sso/google/callback     → exchange code, login/create user
  GET  /auth/sso/microsoft           → redirect to Microsoft consent
  GET  /auth/sso/microsoft/callback  → exchange code, login/create user
"""
import httpx
import secrets
import random
import logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import User, UserRole, OAuthAccount, AuditLog
from app.auth import create_access_token
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/sso", tags=["sso"])

_COLORS = ["#6366f1","#8b5cf6","#ec4899","#f59e0b","#10b981","#3b82f6","#ef4444","#14b8a6"]

GOOGLE_AUTH  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_INFO  = "https://www.googleapis.com/oauth2/v3/userinfo"


@router.get("/google")
async def google_login(request: Request):
    if not settings.GOOGLE_CLIENT_ID:
        return JSONResponse({"error": "Google SSO not configured"}, status_code=501)
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    params = "&".join([
        f"client_id={settings.GOOGLE_CLIENT_ID}",
        f"redirect_uri={settings.GOOGLE_REDIRECT_URI}",
        "response_type=code",
        "scope=openid%20email%20profile",
        f"state={state}",
        "access_type=offline",
        "prompt=select_account",
    ])
    return RedirectResponse(f"{GOOGLE_AUTH}?{params}")


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str = None, state: str = None, error: str = None,
    db: AsyncSession = Depends(get_db),
):
    if error or not code:
        return RedirectResponse("/auth/login?sso_error=1")

    async with httpx.AsyncClient(timeout=15) as client:
        tok = await client.post(GOOGLE_TOKEN, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if tok.status_code != 200:
            logger.error(f"Google token error: {tok.text}")
            return RedirectResponse("/auth/login?sso_error=1")
        tokens = tok.json()

        info = await client.get(GOOGLE_INFO,
                                headers={"Authorization": f"Bearer {tokens['access_token']}"})
        if info.status_code != 200:
            return RedirectResponse("/auth/login?sso_error=1")
        p = info.json()

    return await _sso_login(request, db, "google", p["sub"],
                            p.get("email", ""), p.get("name", ""), tokens)


def _ms_auth():  return f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/authorize"
def _ms_token(): return f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0/token"
MS_ME = "https://graph.microsoft.com/v1.0/me"


@router.get("/microsoft")
async def microsoft_login(request: Request):
    if not settings.MICROSOFT_CLIENT_ID:
        return JSONResponse({"error": "Microsoft SSO not configured"}, status_code=501)
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    params = "&".join([
        f"client_id={settings.MICROSOFT_CLIENT_ID}",
        f"redirect_uri={settings.MICROSOFT_REDIRECT_URI}",
        "response_type=code",
        "scope=openid%20email%20profile%20User.Read",
        f"state={state}",
        "response_mode=query",
    ])
    return RedirectResponse(f"{_ms_auth()}?{params}")


@router.get("/microsoft/callback")
async def microsoft_callback(
    request: Request,
    code: str = None, state: str = None, error: str = None,
    db: AsyncSession = Depends(get_db),
):
    if error or not code:
        return RedirectResponse("/auth/login?sso_error=1")

    async with httpx.AsyncClient(timeout=15) as client:
        tok = await client.post(_ms_token(), data={
            "code": code,
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
            "grant_type": "authorization_code",
            "scope": "openid email profile User.Read",
        })
        if tok.status_code != 200:
            logger.error(f"MS token error: {tok.text}")
            return RedirectResponse("/auth/login?sso_error=1")
        tokens = tok.json()

        me = await client.get(MS_ME,
                              headers={"Authorization": f"Bearer {tokens['access_token']}"})
        if me.status_code != 200:
            return RedirectResponse("/auth/login?sso_error=1")
        p = me.json()

    email = p.get("mail") or p.get("userPrincipalName", "")
    return await _sso_login(request, db, "microsoft", p.get("id", ""),
                            email, p.get("displayName", email), tokens)

async def _sso_login(request, db, provider, provider_uid, email, name, tokens):
    oauth = (await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_uid,
        )
    )).scalar_one_or_none()

    user = None
    if oauth:
        user = (await db.execute(select(User).where(User.id == oauth.user_id))).scalar_one_or_none()
    else:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not user:
            count = (await db.execute(select(func.count(User.id)))).scalar()
            user = User(
                full_name=name or email.split("@")[0],
                email=email,
                hashed_password="",           # SSO-only account
                department="General",
                role=UserRole.super_admin if count == 0 else UserRole.staff,
                avatar_color=random.choice(_COLORS),
                onboarding_complete=(count == 0),
            )
            db.add(user)
            await db.flush()

        db.add(OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_uid,
            email=email,
            access_token=tokens.get("access_token", ""),
            refresh_token=tokens.get("refresh_token", ""),
        ))

    if not user or not user.is_active:
        return RedirectResponse("/auth/login?sso_error=inactive")

    user.is_online = True
    db.add(AuditLog(
        user_id=user.id,
        action=f"sso_login_{provider}",
        resource_type="auth",
        details={"email": email},
        ip_address=request.client.host if request.client else "",
    ))
    await db.commit()

    token = create_access_token({"sub": str(user.id)})
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie("access_token", token, httponly=True, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, samesite="lax")
    resp.set_cookie("ws_token", token, httponly=False,
                    max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, samesite="lax")
    return resp