from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from app.database import init_db
from app.config import settings
from app.routers import auth, dashboard, messages, ask_boss, documents, admin
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting BOSS System...")
    await init_db()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(f"{settings.UPLOAD_DIR}/documents", exist_ok=True)
    logger.info("Database initialized.")
    yield
    logger.info("Shutting down BOSS System.")


app = FastAPI(
    title="BOSS - Business Operating System",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(messages.router)
app.include_router(ask_boss.router)
app.include_router(documents.router)
app.include_router(admin.router)


@app.exception_handler(307)
async def redirect_handler(request: Request, exc):
    return RedirectResponse(url="/auth/login")


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    templates = Jinja2Templates(directory="app/templates")
    return templates.TemplateResponse(
        "errors/403.html",
        {"request": request},
        status_code=403,
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    templates = Jinja2Templates(directory="app/templates")
    return templates.TemplateResponse(
        "errors/404.html",
        {"request": request},
        status_code=404,
    )
