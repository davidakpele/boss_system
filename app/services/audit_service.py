"""
app/services/audit_service.py
──────────────────────────────────────────────────────────────────────────────
The ONE write path to ImmutableAuditLog.

Rules:
  - Only AuditService.log() may insert rows.  No other code touches the table.
  - Errors in audit logging are caught and re-raised as warnings — they must
    never block the main request.
  - The helper is async-safe and works inside both request handlers and
    background tasks.

Usage:
    from app.services.audit_service import AuditService

    await AuditService.log(
        db           = db,
        user         = current_user,
        action       = "document.approve",
        resource_type= "document",
        resource_id  = doc.id,
        resource_name= doc.title,
        details      = {"department": doc.department},
        request      = request,          # optional; extracts IP + UA
    )
"""

from __future__ import annotations

import logging
from typing import Optional, Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ImmutableAuditLog

logger = logging.getLogger(__name__)


class AuditService:

    @staticmethod
    async def log(
        db:            AsyncSession,
        action:        str,
        *,
        user=          None,          # User model instance or None (system events)
        resource_type: str  = None,
        resource_id:   int  = None,
        resource_name: str  = None,
        details:       dict = None,
        status:        str  = "success",
        error_msg:     str  = None,
        request:       Request = None,
        ip_address:    str  = None,
        user_agent:    str  = None,
        session_id:    str  = None,
    ) -> None:
        """
        Append one immutable audit record.  Never raises — catches all errors
        internally so audit failures don't break the request.
        """
        try:
            ip  = ip_address
            ua  = user_agent
            sid = session_id

            if request and not ip:
                ip = request.client.host if request.client else None
            if request and not ua:
                ua = request.headers.get("user-agent")

            tenant_id   = getattr(user, "tenant_id", None)
            user_id     = getattr(user, "id", None)
            user_email  = getattr(user, "email", None)
            user_role   = getattr(user, "role", None)
            if hasattr(user_role, "value"):
                user_role = user_role.value

            entry = ImmutableAuditLog(
                user_id       = user_id,
                user_email    = user_email,
                user_role     = user_role,
                tenant_id     = tenant_id,
                action        = action,
                resource_type = resource_type,
                resource_id   = resource_id,
                resource_name = resource_name,
                details       = details or {},
                status        = status,
                error_msg     = error_msg,
                ip_address    = ip,
                user_agent    = ua,
                session_id    = sid,
            )
            db.add(entry)
            # We don't commit here — caller's transaction covers it.
            # If the caller commits, the log commits atomically.
            # If the caller rolls back, the log also rolls back (correct behaviour —
            # we don't want a log entry for a failed transaction).

        except Exception as exc:
            logger.error(f"[AUDIT] Failed to write audit log for action={action}: {exc}")

    # ── Convenience wrappers ──────────────────────────────────────────────────

    @staticmethod
    async def log_auth(db, user, action: str, request: Request = None, **kw):
        await AuditService.log(db, action, user=user, resource_type="auth",
                               request=request, **kw)

    @staticmethod
    async def log_document(db, user, action: str, doc, request: Request = None, **kw):
        await AuditService.log(
            db, action, user=user,
            resource_type="document",
            resource_id=doc.id,
            resource_name=getattr(doc, "title", None),
            details={"department": getattr(doc, "department", None),
                     "status": str(getattr(doc, "status", ""))},
            request=request, **kw,
        )

    @staticmethod
    async def log_user_mgmt(db, actor, action: str, target_user, request: Request = None, **kw):
        await AuditService.log(
            db, action, user=actor,
            resource_type="user",
            resource_id=target_user.id,
            resource_name=target_user.email,
            details={"role": str(target_user.role), "department": target_user.department},
            request=request, **kw,
        )


    # ── Query helpers (read path) ─────────────────────────────────────────────

    @staticmethod
    async def query(
        db:          AsyncSession,
        *,
        tenant_id:   int  = None,
        user_id:     int  = None,
        action:      str  = None,
        resource_type: str = None,
        days:        int  = 90,
        limit:       int  = 500,
        offset:      int  = 0,
    ):
        """
        Flexible audit log query.  All filters are optional and additive.
        Returns list of ImmutableAuditLog rows.
        """
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import select, and_

        since = datetime.now(timezone.utc) - timedelta(days=days)
        clauses = [ImmutableAuditLog.created_at >= since]

        if tenant_id is not None:
            clauses.append(ImmutableAuditLog.tenant_id == tenant_id)
        if user_id is not None:
            clauses.append(ImmutableAuditLog.user_id == user_id)
        if action:
            clauses.append(ImmutableAuditLog.action.ilike(f"{action}%"))
        if resource_type:
            clauses.append(ImmutableAuditLog.resource_type == resource_type)

        stmt = (
            select(ImmutableAuditLog)
            .where(and_(*clauses))
            .order_by(ImmutableAuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return result.scalars().all()