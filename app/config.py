# Configuration settings for the BOSS System application. src/config.py
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:root@localhost:5432/boss_system"
    SECRET_KEY: str = "3hbXrhqhmvPD0bVq9Ce4hxTqALG701J7jRXyfKjqtzDPIlbdJ8YMI"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "codellama:7b-instruct-q4_K_M"
    UPLOAD_DIR: str = "uploads"
    MAX_FILE_SIZE_MB: int = 50
    APP_NAME: str = "BOSS System"
    APP_VERSION: str = "1.0.0"
    GOOGLE_CLIENT_ID:     str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # ── SSO ──────────────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/auth/sso/google/callback"
 
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""
    MICROSOFT_TENANT_ID: str = "common"
    MICROSOFT_REDIRECT_URI: str = "http://localhost:8000/auth/sso/microsoft/callback"
 
    # ── IP Allowlist ──────────────────────────────────────────────────────
    IP_ALLOWLIST_ENABLED: bool = False
 
    # ── Web Push (VAPID) ─────────────────────────────────────────────────
    # Generate keys once:
    #   python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print(v.public_key_urlsafe,v.private_key_urlsafe)"
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_CLAIMS_EMAIL: str = "admin@yourcompany.com"
 
    class Config:
        env_file = ".env"
        extra = "ignore"
 
 
settings = Settings()