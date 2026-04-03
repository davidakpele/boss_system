# main.py  — complete file, replace existing
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.database import init_db
from app.config import settings
from app.routers import auth, bcc, dashboard, messages, ask_boss, documents, admin
from app.routers import business_ops, sso, push
from app.middleware.ip_allowlist import IPAllowlistMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    for d in [settings.UPLOAD_DIR,
              f"{settings.UPLOAD_DIR}/documents",
              f"{settings.UPLOAD_DIR}/messages",
              f"{settings.UPLOAD_DIR}/cvs"]:
        os.makedirs(d, exist_ok=True)
    yield


app = FastAPI(title="BOSS System", version=settings.APP_VERSION,
              lifespan=lifespan, docs_url=None, redoc_url=None)

# ── Middleware (order matters — session BEFORE IP check) ─────────────────────
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.add_middleware(IPAllowlistMiddleware)

# ── Static mounts ─────────────────────────────────────────────────────────────
app.mount("/static",  StaticFiles(directory="app/static"),      name="static")
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


# ── PWA files at root ─────────────────────────────────────────────────────────
async def pwa_manifest():
    return FileResponse("app/static/manifest.json", media_type="application/manifest+json")
 
@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse("app/static/sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})


# ── Routers ───────────────────────────────────────────────────────────────────
for r in [auth.router, sso.router, push.router, bcc.router,
          dashboard.router, messages.router, ask_boss.router,
          documents.router, admin.router, business_ops.router]:
    app.include_router(r)


# ── Error handlers ────────────────────────────────────────────────────────────
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