# main.py
import asyncio
from datetime import datetime, timedelta
import os
import logging
from contextlib import asynccontextmanager
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
    platform_router.router,
    
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
    

async def _scheduled_backup():
    """Run daily backup at 2am UTC."""
    while True:
        now = datetime.utcnow()
        # Calculate seconds until next 2am
        next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        from app.routers.platform import _run_backup
        from app.database import AsyncSessionLocal
        from app.models import BackupLog
        async with AsyncSessionLocal() as db:
            log = BackupLog(triggered_by="scheduler")
            db.add(log)
            await db.commit()
            await db.refresh(log)
            asyncio.create_task(_run_backup(log.id))