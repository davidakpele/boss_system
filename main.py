# main.py
import asyncio
from datetime import datetime, timedelta
import os
import logging
from contextlib import asynccontextmanager
import select
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import json as _json
from app.database import init_db, AsyncSessionLocal
from app.config import settings
from app.routers import analytics, auth, bcc, dashboard, messages, ask_boss, documents, admin, whatsapp
from app.routers import business_ops, sso, push
from app.middleware.ip_allowlist import IPAllowlistMiddleware
from app.routers import calls as calls_router
from app.routers import ai_features
from app.security_service import seed_default_admin, DataRetentionService
from app.routers.auth import require_admin
from app.database import get_db
from app.routers import platform as platform_router
from app.middleware.rate_limiter import RateLimiterMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")


# ── Jinja2 custom filters ─────────────────────────────────────────────────────
def _fromjson(s):
    if not s:
        return {}
    try:
        return _json.loads(s)
    except Exception:
        return {}

templates.env.filters["fromjson"] = _fromjson


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Create all DB tables (app models + security models)
    await init_db()

    # 2. Create upload directories
    for d in [settings.UPLOAD_DIR,
              f"{settings.UPLOAD_DIR}/documents",
              f"{settings.UPLOAD_DIR}/messages",
              f"{settings.UPLOAD_DIR}/cvs"]:
        os.makedirs(d, exist_ok=True)

    # 3. Seed default super-admin (idempotent — skips if already exists)
    async with AsyncSessionLocal() as db:
        await seed_default_admin(db)

    yield


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="BOSS System",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

# ── Middleware (order matters — session BEFORE IP check) ──────────────────────
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.add_middleware(IPAllowlistMiddleware)

# ── Static mounts ─────────────────────────────────────────────────────────────
app.mount("/static",  StaticFiles(directory="app/static"),        name="static")
app.mount("/public",  StaticFiles(directory="public"),       name="public") 
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


# ── PWA files at root ─────────────────────────────────────────────────────────
@app.get("/manifest.json", include_in_schema=False)
async def pwa_manifest():
    return FileResponse("app/static/manifest.json", media_type="application/manifest+json")

@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse(
        "app/static/sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


# ── Routers
for r in [
    auth.router, sso.router, push.router, bcc.router,
    analytics.router, ai_features.router, dashboard.router,
    messages.router, ask_boss.router, documents.router,
    admin.router, business_ops.router, whatsapp.router,
    platform_router.router, calls_router.router
    
]:
    app.include_router(r)

from app.security_service import LockoutService

@app.post("/admin/security/unlock/{email}", tags=["admin-security"])
async def admin_unlock_account(
    email: str,
    _: object = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Instantly unlock a locked-out account."""
    ok = await LockoutService.unlock(db, email)
    return JSONResponse({"unlocked": ok, "email": email})


@app.post("/admin/security/lock/{email}", tags=["admin-security"])
async def admin_lock_account(
    email: str,
    reason: str = "Manually locked by admin",
    _: object = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually lock an account indefinitely."""
    await LockoutService.manual_lock(db, email, reason)
    return JSONResponse({"locked": True, "email": email})


@app.post("/admin/security/retention/run", tags=["admin-security"])
async def admin_run_retention(
    _: object = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger data-retention purge (normally scheduled nightly)."""
    results = await DataRetentionService.run_all(db)
    return JSONResponse({"purged": results})


# ── Error handlers 
@app.exception_handler(403)
async def handle_403(request: Request, exc):
    return templates.TemplateResponse(
        request=request, name="errors/403.html", context={}, status_code=403)

@app.exception_handler(404)
async def handle_404(request: Request, exc):
    if request.url.path in ("/favicon.ico",) or request.url.path.startswith("/.well-known"):
        return HTMLResponse("", status_code=204)
    return templates.TemplateResponse(
        request=request, name="errors/404.html", context={}, status_code=404)        

async def _scheduled_message_worker():
    """Check every 30s for messages whose send time has arrived."""
    import asyncio
    import logging
    from datetime import datetime                          # ← CLASS not module
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models import ScheduledMessage, Message, User
    from app.services.websocket_manager import manager
 
    logger = logging.getLogger("main")
 
    while True:
        await asyncio.sleep(30)
        try:
            now = datetime.utcnow()
            async with AsyncSessionLocal() as db:
                due = (await db.execute(
                    select(ScheduledMessage).where(
                        ScheduledMessage.sent      == False,
                        ScheduledMessage.cancelled == False,
                        ScheduledMessage.scheduled_at <= now,
                    )
                )).scalars().all()
 
                for sm in due:
                    sender = (await db.execute(
                        select(User).where(User.id == sm.sender_id)
                    )).scalar_one_or_none()
                    if not sender:
                        sm.cancelled = True
                        continue
 
                    msg = Message(
                        channel_id    = sm.channel_id,
                        sender_id     = sm.sender_id,
                        content       = sm.content,
                        message_type  = "text",
                        is_deleted    = False,
                        is_ai_extracted = False,
                    )
                    db.add(msg)
                    await db.flush()
 
                    sm.sent    = True
                    sm.sent_at = now
                    await db.commit()
                    await db.refresh(msg)
 
                    await manager.broadcast_to_channel(sm.channel_id, {
                        "type":         "message",
                        "id":           msg.id,
                        "content":      msg.content,
                        "sender_id":    msg.sender_id,
                        "sender_name":  sender.full_name,
                        "avatar_color": sender.avatar_color,
                        "created_at":   msg.created_at.isoformat() if msg.created_at else "",
                        "message_type": "text",
                        "is_deleted":   False,
                        "reply_to_id":  None,
                        "thread_count": 0,
                        "is_thread_reply": False,
                        "reactions":    [],
                    })
                    logger.info(f"Delivered scheduled message {sm.id} → channel {sm.channel_id}")
 
        except Exception as e:
            logger.error(f"Scheduled message worker error: {e}", exc_info=True)

asyncio.create_task(_scheduled_message_worker())