# app/security_models.py
"""
Security feature tables.  All inherit from the SAME Base instance as
app/models.py — so the single create_all() call in database.init_db()
covers every table automatically.
"""

from sqlalchemy import (
    Column, Integer, String, Boolean,
    DateTime, ForeignKey, JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

# ⚠️  Import Base from app.models so every table shares one MetaData object
from app.models import Base


# ─────────────────────────────────────────────────────────────────────────────
#  Session management
# ─────────────────────────────────────────────────────────────────────────────

class UserSession(Base):
    """One row per active login.  Revoked on logout or by admin."""
    __tablename__ = "user_sessions"

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_token = Column(String(256), unique=True, nullable=False, index=True)
    ip_address    = Column(String(50))
    user_agent    = Column(String(512))
    device_name   = Column(String(200))   # e.g. "Chrome on Windows (Desktop)"
    is_revoked    = Column(Boolean, default=False)
    last_active   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expires_at    = Column(DateTime(timezone=True), nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", foreign_keys=[user_id])


# ─────────────────────────────────────────────────────────────────────────────
#  Login attempt tracking / lockout
# ─────────────────────────────────────────────────────────────────────────────

class LoginAttempt(Base):
    """Every login attempt (success or failure) per email + IP."""
    __tablename__ = "login_attempts"

    id         = Column(Integer, primary_key=True, index=True)
    email      = Column(String(255), nullable=False, index=True)
    ip_address = Column(String(50),  nullable=False, index=True)
    success    = Column(Boolean, default=False)
    user_agent = Column(String(512))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AccountLockout(Base):
    """Written when the failure threshold is hit.  Auto-expires or admin-cleared."""
    __tablename__ = "account_lockouts"

    id        = Column(Integer, primary_key=True, index=True)
    email     = Column(String(255), unique=True, nullable=False, index=True)
    locked_at = Column(DateTime(timezone=True), server_default=func.now())
    unlock_at = Column(DateTime(timezone=True), nullable=False)
    is_manual = Column(Boolean, default=False)
    reason    = Column(String(255))


# ─────────────────────────────────────────────────────────────────────────────
#  Two-Factor Authentication (TOTP)
# ─────────────────────────────────────────────────────────────────────────────

class TwoFactorSecret(Base):
    """TOTP secret per user. is_enabled=False until the first OTP is verified."""
    __tablename__ = "two_factor_secrets"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                        unique=True, nullable=False)
    secret     = Column(String(64), nullable=False)
    is_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    enabled_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")


class TwoFactorBackupCode(Base):
    """Single-use recovery codes — stored as bcrypt hashes."""
    __tablename__ = "two_factor_backup_codes"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code_hash  = Column(String(255), nullable=False)
    used_at    = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


# ─────────────────────────────────────────────────────────────────────────────
#  API Key management
# ─────────────────────────────────────────────────────────────────────────────

class APIKey(Base):
    """Long-lived API keys.  Raw key shown once; SHA-256 hash stored."""
    __tablename__ = "api_keys"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name       = Column(String(200), nullable=False)
    key_hash   = Column(String(128), unique=True, nullable=False, index=True)
    key_prefix = Column(String(12),  nullable=False)   # first chars shown in UI
    scopes     = Column(JSON, default=list)
    is_active  = Column(Boolean, default=True)
    last_used  = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


# ─────────────────────────────────────────────────────────────────────────────
#  Password history (prevent reuse)
# ─────────────────────────────────────────────────────────────────────────────

class PasswordHistory(Base):
    """Keeps last N bcrypt hashes so users cannot reuse recent passwords."""
    __tablename__ = "password_history"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    hash       = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


# ─────────────────────────────────────────────────────────────────────────────
#  Data-retention policy
# ─────────────────────────────────────────────────────────────────────────────

class DataRetentionPolicy(Base):
    """Admin-configured per-resource retention rules."""
    __tablename__ = "data_retention_policies"

    id          = Column(Integer, primary_key=True, index=True)
    resource    = Column(String(100), unique=True, nullable=False)
    retain_days = Column(Integer, nullable=False, default=365)
    action      = Column(String(20), default="delete")   # delete | anonymise
    is_active   = Column(Boolean, default=True)
    created_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    creator = relationship("User", foreign_keys=[created_by])


# ─────────────────────────────────────────────────────────────────────────────
#  Field-level encryption audit
# ─────────────────────────────────────────────────────────────────────────────

class EncryptedFieldAudit(Base):
    """Records who decrypted which field and when."""
    __tablename__ = "encrypted_field_audits"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    table_name = Column(String(100), nullable=False)
    field_name = Column(String(100), nullable=False)
    record_id  = Column(Integer, nullable=False)
    action     = Column(String(20), nullable=False)   # encrypt | decrypt | rekey
    ip_address = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", foreign_keys=[user_id])