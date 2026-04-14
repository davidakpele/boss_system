# app/security_service.py
"""
Enterprise security service layer.  All configuration is read from
`app.config.settings` — no separate config class needed.

Services:
  PasswordPolicy       – validate rules & check history
  LockoutService       – track failures, lock/unlock accounts
  SessionService       – create, validate, list, revoke sessions
  TwoFactorService     – TOTP setup, enable, verify, disable, backup codes
  APIKeyService        – generate, validate, list, revoke API keys
  FieldEncryption      – Fernet field-level encryption (opt-in)
  DataRetentionService – apply retention/purge rules
  seed_default_admin   – idempotent super-admin creation on startup
"""

from __future__ import annotations

import hashlib
import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import pyotp
from sqlalchemy import select, func, delete, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole, AuditLog
from app.security_models import (
    AccountLockout, LoginAttempt,
    TwoFactorSecret, TwoFactorBackupCode,
    UserSession, APIKey,
    PasswordHistory, DataRetentionPolicy,
)
from app.config import settings 

try:
    from cryptography.fernet import Fernet
    _FERNET_AVAILABLE = True
except ImportError:
    _FERNET_AVAILABLE = False

class PasswordPolicy:

    @staticmethod
    def validate(password: str) -> list[str]:
        """Return a list of violation strings (empty list = password is valid)."""
        errors: list[str] = []

        if len(password) < settings.PASSWORD_MIN_LENGTH:
            errors.append(f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters.")

        if settings.PASSWORD_REQUIRE_UPPERCASE and not re.search(r"[A-Z]", password):
            errors.append("Password must contain at least one uppercase letter.")

        if settings.PASSWORD_REQUIRE_LOWERCASE and not re.search(r"[a-z]", password):
            errors.append("Password must contain at least one lowercase letter.")

        if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r"\d", password):
            errors.append("Password must contain at least one digit.")

        if settings.PASSWORD_REQUIRE_SPECIAL and not re.search(
            r"[!@#$%^&*()\-_=+\[\]{}|;:',.<>?/`~\"\\]", password
        ):
            errors.append("Password must contain at least one special character.")

        return errors

    @staticmethod
    def hint() -> str:
        parts = [f"at least {settings.PASSWORD_MIN_LENGTH} characters"]
        if settings.PASSWORD_REQUIRE_UPPERCASE:
            parts.append("an uppercase letter")
        if settings.PASSWORD_REQUIRE_LOWERCASE:
            parts.append("a lowercase letter")
        if settings.PASSWORD_REQUIRE_DIGIT:
            parts.append("a digit")
        if settings.PASSWORD_REQUIRE_SPECIAL:
            parts.append("a special character")
        return "Password must contain: " + ", ".join(parts) + "."

    @staticmethod
    async def check_history(db: AsyncSession, user_id: int, new_password: str) -> bool:
        """Return True if new_password matches any of the last N stored hashes."""
        depth = settings.PASSWORD_HISTORY_DEPTH
        result = await db.execute(
            select(PasswordHistory)
            .where(PasswordHistory.user_id == user_id)
            .order_by(PasswordHistory.created_at.desc())
            .limit(depth)
        )
        for ph in result.scalars():
            if bcrypt.checkpw(new_password.encode(), ph.hash.encode()):
                return True
        return False

    @staticmethod
    async def record(db: AsyncSession, user_id: int, new_hash: str) -> None:
        """Append the current bcrypt hash to the history table."""
        db.add(PasswordHistory(user_id=user_id, hash=new_hash))

class LockoutService:

    @staticmethod
    async def record_attempt(
        db: AsyncSession,
        email: str,
        ip_address: str,
        success: bool,
        user_agent: str = "",
    ) -> None:
        db.add(LoginAttempt(
            email=email, ip_address=ip_address,
            success=success, user_agent=user_agent,
        ))
        if not success:
            await LockoutService._maybe_lock(db, email)
        await db.commit()

    @staticmethod
    async def _maybe_lock(db: AsyncSession, email: str) -> None:
        window = datetime.now(timezone.utc) - timedelta(minutes=settings.LOCKOUT_WINDOW_MINUTES)
        result = await db.execute(
            select(func.count(LoginAttempt.id)).where(
                and_(
                    LoginAttempt.email == email,
                    LoginAttempt.success.is_(False),
                    LoginAttempt.created_at >= window,
                )
            )
        )
        failures = result.scalar() or 0

        if failures >= settings.MAX_LOGIN_ATTEMPTS:
            unlock_at = datetime.now(timezone.utc) + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
            existing = (await db.execute(
                select(AccountLockout).where(AccountLockout.email == email)
            )).scalar_one_or_none()

            if existing:
                existing.locked_at = datetime.now(timezone.utc)
                existing.unlock_at = unlock_at
                existing.reason    = "Too many failed login attempts"
            else:
                db.add(AccountLockout(
                    email=email, unlock_at=unlock_at,
                    reason="Too many failed login attempts",
                ))

    @staticmethod
    async def is_locked(db: AsyncSession, email: str) -> tuple[bool, Optional[datetime]]:
        """Returns (is_locked, unlock_at).  Expired lockouts are auto-deleted."""
        result = await db.execute(
            select(AccountLockout).where(AccountLockout.email == email)
        )
        lockout = result.scalar_one_or_none()
        if not lockout:
            return False, None

        now = datetime.now(timezone.utc)
        if not lockout.is_manual and lockout.unlock_at <= now:
            await db.delete(lockout)
            await db.commit()
            return False, None

        return True, lockout.unlock_at

    @staticmethod
    async def unlock(db: AsyncSession, email: str) -> bool:
        result = await db.execute(
            select(AccountLockout).where(AccountLockout.email == email)
        )
        lockout = result.scalar_one_or_none()
        if lockout:
            await db.delete(lockout)
            await db.commit()
            return True
        return False

    @staticmethod
    async def manual_lock(db: AsyncSession, email: str, reason: str = "") -> None:
        """Lock an account indefinitely (admin action)."""
        unlock_at = datetime.now(timezone.utc) + timedelta(days=3650)
        existing = (await db.execute(
            select(AccountLockout).where(AccountLockout.email == email)
        )).scalar_one_or_none()
        if existing:
            existing.locked_at = datetime.now(timezone.utc)
            existing.unlock_at = unlock_at
            existing.is_manual = True
            existing.reason    = reason
        else:
            db.add(AccountLockout(
                email=email, unlock_at=unlock_at,
                is_manual=True, reason=reason,
            ))
        await db.commit()

class SessionService:

    @staticmethod
    def _parse_device(user_agent: str) -> str:
        ua = user_agent.lower()
        device  = "Mobile" if ("mobile" in ua or "android" in ua) else (
                  "Tablet" if ("tablet" in ua or "ipad" in ua) else "Desktop")
        browser = ("Chrome"  if "chrome"  in ua and "edg" not in ua else
                   "Firefox" if "firefox" in ua else
                   "Safari"  if "safari"  in ua and "chrome" not in ua else
                   "Edge"    if "edg"     in ua else "Browser")
        os_     = ("Windows" if "windows" in ua else
                   "macOS"   if "mac"     in ua else
                   "Android" if "android" in ua else
                   "iOS"     if ("iphone" in ua or "ipad" in ua) else
                   "Linux"   if "linux"   in ua else "Unknown OS")
        return f"{browser} on {os_} ({device})"

    @staticmethod
    async def create(
        db: AsyncSession, user_id: int, ip_address: str, user_agent: str
    ) -> UserSession:
        token      = secrets.token_urlsafe(64)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.SESSION_EXPIRE_MINUTES)
        session    = UserSession(
            user_id=user_id, session_token=token,
            ip_address=ip_address, user_agent=user_agent,
            device_name=SessionService._parse_device(user_agent),
            expires_at=expires_at,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    @staticmethod
    async def get_active(db: AsyncSession, user_id: int) -> list[UserSession]:
        now    = datetime.now(timezone.utc)
        result = await db.execute(
            select(UserSession).where(
                and_(
                    UserSession.user_id == user_id,
                    UserSession.is_revoked.is_(False),
                    UserSession.expires_at > now,
                )
            ).order_by(UserSession.last_active.desc())
        )
        return list(result.scalars())

    @staticmethod
    async def revoke(db: AsyncSession, session_id: int, user_id: int) -> bool:
        result = await db.execute(
            select(UserSession).where(
                and_(UserSession.id == session_id, UserSession.user_id == user_id)
            )
        )
        session = result.scalar_one_or_none()
        if session:
            session.is_revoked = True
            await db.commit()
            return True
        return False

    @staticmethod
    async def revoke_all(db: AsyncSession, user_id: int, except_token: str = "") -> int:
        result = await db.execute(
            select(UserSession).where(
                and_(UserSession.user_id == user_id, UserSession.is_revoked.is_(False))
            )
        )
        count = 0
        for s in result.scalars():
            if s.session_token != except_token:
                s.is_revoked = True
                count += 1
        await db.commit()
        return count

    @staticmethod
    async def validate(db: AsyncSession, token: str) -> Optional[UserSession]:
        now    = datetime.now(timezone.utc)
        result = await db.execute(
            select(UserSession).where(
                and_(
                    UserSession.session_token == token,
                    UserSession.is_revoked.is_(False),
                    UserSession.expires_at > now,
                )
            )
        )
        session = result.scalar_one_or_none()
        if session:
            session.last_active = now
            await db.commit()
        return session

class TwoFactorService:

    @staticmethod
    def _totp(secret: str) -> pyotp.TOTP:
        return pyotp.TOTP(secret, digits=6, interval=30, issuer=settings.TOTP_ISSUER)

    @staticmethod
    async def setup(db: AsyncSession, user: User) -> dict:
        """
        Generate (or regenerate) a TOTP secret for the user.
        Returns {"secret": …, "qr_uri": …, "qr_url": …}.
        2FA is NOT enabled until enable() is called.
        """
        secret = pyotp.random_base32()
        totp   = TwoFactorService._totp(secret)
        uri    = totp.provisioning_uri(name=user.email, issuer_name=settings.TOTP_ISSUER)

        existing = (await db.execute(
            select(TwoFactorSecret).where(TwoFactorSecret.user_id == user.id)
        )).scalar_one_or_none()

        if existing:
            existing.secret     = secret
            existing.is_enabled = False
            existing.enabled_at = None
        else:
            db.add(TwoFactorSecret(user_id=user.id, secret=secret))

        await db.commit()

        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={uri}"
        return {"secret": secret, "qr_uri": uri, "qr_url": qr_url}

    @staticmethod
    async def enable(db: AsyncSession, user_id: int, otp_code: str) -> tuple[bool, list[str]]:
        """
        Verify the first OTP after setup → enable 2FA → return 8 backup codes.
        Returns (success, [raw_codes]).
        """
        record = (await db.execute(
            select(TwoFactorSecret).where(TwoFactorSecret.user_id == user_id)
        )).scalar_one_or_none()

        if not record:
            return False, []

        if not TwoFactorService._totp(record.secret).verify(otp_code, valid_window=1):
            return False, []

        record.is_enabled = True
        record.enabled_at = datetime.now(timezone.utc)

        # Purge old backup codes then generate fresh ones
        await db.execute(
            delete(TwoFactorBackupCode).where(TwoFactorBackupCode.user_id == user_id)
        )

        alphabet  = string.ascii_uppercase + string.digits
        raw_codes = [
            "".join(secrets.choice(alphabet) for _ in range(8))
            for _ in range(settings.BACKUP_CODE_COUNT)
        ]
        for code in raw_codes:
            hashed = bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode()
            db.add(TwoFactorBackupCode(user_id=user_id, code_hash=hashed))

        await db.commit()
        return True, raw_codes

    @staticmethod
    async def verify(db: AsyncSession, user_id: int, code: str) -> bool:
        """Verify a TOTP code OR a backup code.  Returns True on success."""
        record = (await db.execute(
            select(TwoFactorSecret).where(
                and_(
                    TwoFactorSecret.user_id == user_id,
                    TwoFactorSecret.is_enabled.is_(True),
                )
            )
        )).scalar_one_or_none()

        if not record:
            return True  
        if TwoFactorService._totp(record.secret).verify(code, valid_window=1):
            return True

        result = await db.execute(
            select(TwoFactorBackupCode).where(
                and_(
                    TwoFactorBackupCode.user_id == user_id,
                    TwoFactorBackupCode.used_at.is_(None),
                )
            )
        )
        for bc in result.scalars():
            if bcrypt.checkpw(code.encode(), bc.code_hash.encode()):
                bc.used_at = datetime.now(timezone.utc)
                await db.commit()
                return True

        return False

    @staticmethod
    async def disable(db: AsyncSession, user_id: int) -> bool:
        record = (await db.execute(
            select(TwoFactorSecret).where(TwoFactorSecret.user_id == user_id)
        )).scalar_one_or_none()
        if record:
            record.is_enabled = False
            await db.execute(
                delete(TwoFactorBackupCode).where(TwoFactorBackupCode.user_id == user_id)
            )
            await db.commit()
            return True
        return False

    @staticmethod
    async def is_enabled(db: AsyncSession, user_id: int) -> bool:
        record = (await db.execute(
            select(TwoFactorSecret).where(
                and_(
                    TwoFactorSecret.user_id == user_id,
                    TwoFactorSecret.is_enabled.is_(True),
                )
            )
        )).scalar_one_or_none()
        return record is not None

class APIKeyService:

    PREFIX = "boss_"

    @staticmethod
    def _hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: int,
        name: str,
        scopes: list[str] | None = None,
        expires_in_days: int | None = None,
    ) -> tuple[str, APIKey]:
        """
        Returns (raw_key, APIKey).
        The raw key is shown once — never retrievable again.
        """
        raw    = APIKeyService.PREFIX + secrets.token_urlsafe(40)
        hashed = APIKeyService._hash(raw)
        prefix = raw[:12]

        if expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        elif settings.API_KEY_DEFAULT_EXPIRY_DAYS:
            expires_at = datetime.now(timezone.utc) + timedelta(days=settings.API_KEY_DEFAULT_EXPIRY_DAYS)
        else:
            expires_at = None

        key = APIKey(
            user_id=user_id, name=name,
            key_hash=hashed, key_prefix=prefix,
            scopes=scopes or [], expires_at=expires_at,
        )
        db.add(key)
        await db.commit()
        await db.refresh(key)
        return raw, key

    @staticmethod
    async def validate(db: AsyncSession, raw_key: str) -> Optional[APIKey]:
        hashed = APIKeyService._hash(raw_key)
        now    = datetime.now(timezone.utc)
        result = await db.execute(
            select(APIKey).where(
                and_(APIKey.key_hash == hashed, APIKey.is_active.is_(True))
            )
        )
        key = result.scalar_one_or_none()
        if key is None:
            return None
        if key.expires_at and key.expires_at <= now:
            return None
        key.last_used = now
        await db.commit()
        return key

    @staticmethod
    async def revoke(db: AsyncSession, key_id: int, user_id: int) -> bool:
        result = await db.execute(
            select(APIKey).where(and_(APIKey.id == key_id, APIKey.user_id == user_id))
        )
        key = result.scalar_one_or_none()
        if key:
            key.is_active  = False
            key.revoked_at = datetime.now(timezone.utc)
            await db.commit()
            return True
        return False

    @staticmethod
    async def list_for_user(db: AsyncSession, user_id: int) -> list[APIKey]:
        result = await db.execute(
            select(APIKey)
            .where(APIKey.user_id == user_id)
            .order_by(APIKey.created_at.desc())
        )
        return list(result.scalars())

class FieldEncryption:
    """
    Transparent Fernet encryption for sensitive column values.

    Encrypted values are prefixed with "enc::" so code can distinguish them
    from unencrypted legacy data without a schema change.

    Usage:
        stored  = FieldEncryption.encrypt("secret value")
        plain   = FieldEncryption.decrypt(stored)
    """

    PREFIX  = "enc::"
    _fernet = None

    @classmethod
    def _get_fernet(cls):
        if cls._fernet is None:
            key = settings.FIELD_ENCRYPTION_KEY
            if not key:
                raise RuntimeError(
                    "Set FIELD_ENCRYPTION_KEY in your .env file.\n"
                    "Generate one with:\n"
                    "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                )
            if not _FERNET_AVAILABLE:
                raise RuntimeError("Run: pip install cryptography")
            cls._fernet = Fernet(key.encode())
        return cls._fernet

    @classmethod
    def encrypt(cls, value: str) -> str:
        if value.startswith(cls.PREFIX):
            return value 
        return cls.PREFIX + cls._get_fernet().encrypt(value.encode()).decode()

    @classmethod
    def decrypt(cls, value: str) -> str:
        if not value.startswith(cls.PREFIX):
            return value 
        try:
            return cls._get_fernet().decrypt(value[len(cls.PREFIX):].encode()).decode()
        except Exception:
            raise ValueError("Field decryption failed — wrong key or corrupted data.")

    @classmethod
    def is_encrypted(cls, value: str) -> bool:
        return isinstance(value, str) and value.startswith(cls.PREFIX)

class DataRetentionService:
    """
    Enforce configured retention policies.
    Call run_all() from a nightly scheduler or the admin endpoint.
    """
    RESOURCE_MAP = {
        "audit_logs":     ("app.models.AuditLog",              "created_at"),
        "login_attempts": ("app.security_models.LoginAttempt", "created_at"),
        "messages":       ("app.models.Message",               "created_at"),
    }

    @staticmethod
    async def seed_defaults(db: AsyncSession) -> None:
        """Ensure default policies exist (idempotent)."""
        defaults = [
            ("audit_logs",     settings.AUDIT_LOG_RETAIN_DAYS,    "delete"),
            ("login_attempts", settings.LOGIN_ATTEMPT_RETAIN_DAYS, "delete"),
            ("messages",       settings.MESSAGE_RETAIN_DAYS,       "delete"),
        ]
        for resource, days, action in defaults:
            existing = (await db.execute(
                select(DataRetentionPolicy).where(DataRetentionPolicy.resource == resource)
            )).scalar_one_or_none()
            if not existing:
                db.add(DataRetentionPolicy(resource=resource, retain_days=days, action=action))
        await db.commit()

    @staticmethod
    async def run_all(db: AsyncSession) -> dict[str, int]:
        """Execute all active policies. Returns {resource: rows_purged}."""
        import importlib
        results: dict[str, int] = {}

        result_set = await db.execute(
            select(DataRetentionPolicy).where(DataRetentionPolicy.is_active.is_(True))
        )
        for policy in result_set.scalars():
            mapping = DataRetentionService.RESOURCE_MAP.get(policy.resource)
            if not mapping:
                continue
            model_path, date_col = mapping
            module_path, class_name = model_path.rsplit(".", 1)
            try:
                mod   = importlib.import_module(module_path)
                Model = getattr(mod, class_name)
            except (ImportError, AttributeError):
                continue

            cutoff  = datetime.now(timezone.utc) - timedelta(days=policy.retain_days)
            col_attr = getattr(Model, date_col)
            stmt    = delete(Model).where(col_attr < cutoff)
            res     = await db.execute(stmt)
            await db.commit()
            results[policy.resource] = res.rowcount

        return results

async def seed_default_admin(db: AsyncSession) -> None:
    """
    Creates the hardcoded super-admin on first startup.
    Completely idempotent — skips silently if the email already exists.

    Credentials come from settings.DEFAULT_ADMIN_EMAIL / DEFAULT_ADMIN_PASSWORD.
    """
    email = settings.DEFAULT_ADMIN_EMAIL

    existing = (await db.execute(
        select(User).where(User.email == email)
    )).scalar_one_or_none()

    if existing:
        return

    import random
    AVATAR_COLORS = ["#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
                     "#10b981", "#3b82f6", "#ef4444", "#14b8a6"]

    hashed = bcrypt.hashpw(
        settings.DEFAULT_ADMIN_PASSWORD.encode(), bcrypt.gensalt()
    ).decode()

    admin = User(
        full_name=settings.DEFAULT_ADMIN_NAME,
        email=email,
        hashed_password=hashed,
        department=settings.DEFAULT_ADMIN_DEPARTMENT,
        role=UserRole.super_admin,
        is_active=True,
        avatar_color=random.choice(AVATAR_COLORS),
        onboarding_complete=True,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    await DataRetentionService.seed_defaults(db)

    import logging
    logging.getLogger(__name__).info(
        f"[BOSS] Default super-admin created → {email}"
    )