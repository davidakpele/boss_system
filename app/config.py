#src/config.py
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
 

    VAPID_PUBLIC_KEY: str = "BDthBjOdUX9oTA7HWSFJaFTc9JUxNuiF3gkEmam0vMJ-tZYUQnwqVqG4NMuNR_moxnwhTjNSPVR5X6CjclzBZpw"
    VAPID_PRIVATE_KEY: str = "9OxBb4E7j1o2XIy25E9VHQ_55njhIxFPBU0ykub7RDc"
    VAPID_CLAIMS_EMAIL: str = "admin@yourcompany.com"
 
    DEFAULT_ADMIN_EMAIL: str = "admin@aol.com"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"
    DEFAULT_ADMIN_NAME: str = "David Ak"
    DEFAULT_ADMIN_DEPARTMENT: str = "Management"
    
    LOCKOUT_WINDOW_MINUTES: int = 15
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 30
    
    SESSION_EXPIRE_MINUTES: int = 480
    
    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_HISTORY_DEPTH: int = 5
    PASSWORD_REQUIRE_SPECIAL: bool = True
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_LOWERCASE: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    
    class Config:
        env_file = ".env"
        extra = "ignore"
 
 
settings = Settings()