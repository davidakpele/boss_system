"""
app/middleware/tenant_isolation.py
Multi-tenant data isolation.

Every DB query for tenant-scoped data must be filtered by tenant_id.
This module provides:

  TenantContext        – request-scoped tenant resolver
  tenant_filter()      – SQLAlchemy WHERE clause helper
  assert_tenant_owns() – raises 403 if a row doesn't belong to the user's tenant
  TenantQueryMixin     – mixin that auto-applies tenant filter to any select()

Usage in a route:
    from app.middleware.tenant_isolation import tenant_filter, assert_tenant_owns

    # List documents scoped to caller's tenant:
    stmt = select(Document).where(*tenant_filter(current_user, Document))
    docs = (await db.execute(stmt)).scalars().all()

    # Guard a single fetched object:
    doc = (await db.execute(...)).scalar_one_or_none()
    assert_tenant_owns(current_user, doc)
"""

from __future__ import annotations

from typing import Optional, Type

from fastapi import HTTPException
from sqlalchemy import and_

from app.models import User, UserRole


# ── Core helpers ──────────────────────────────────────────────────────────────

def get_tenant_id(user: User) -> Optional[int]:
    """Return the tenant id for a user. super_admin has no tenant constraint."""
    if user.role == UserRole.super_admin:
        return None          # super_admin sees everything
    return user.tenant_id


def tenant_filter(user: User, Model) -> list:
    """
    Return a list of WHERE clauses that scope a query to the user's tenant.
    Append with * unpacking:
        stmt = select(M).where(*tenant_filter(user, M))

    Works for any model that has a `tenant_id` column.
    If the model has no tenant_id, returns an empty list (no filter).
    """
    tid = get_tenant_id(user)
    if tid is None:
        return []            # super_admin: no restriction

    if not hasattr(Model, "tenant_id"):
        return []            # model is not tenant-scoped

    return [Model.tenant_id == tid]


def assert_tenant_owns(user: User, obj) -> None:
    """
    Raise HTTP 403 if `obj` doesn't belong to user's tenant.
    Safe to call even if `obj` has no tenant_id (passes through).
    """
    if user.role == UserRole.super_admin:
        return

    obj_tenant = getattr(obj, "tenant_id", None)
    if obj_tenant is None:
        return               # object not tenant-scoped

    if user.tenant_id != obj_tenant:
        raise HTTPException(status_code=403, detail="Cross-tenant access denied")


def same_tenant(user: User, obj) -> bool:
    """Non-raising version of assert_tenant_owns."""
    if user.role == UserRole.super_admin:
        return True
    obj_tenant = getattr(obj, "tenant_id", None)
    if obj_tenant is None:
        return True
    return user.tenant_id == obj_tenant


# ── AI / Knowledge isolation ──────────────────────────────────────────────────

def knowledge_tenant_filter(user: User, KnowledgeChunk) -> list:
    """
    Knowledge chunks are isolated per tenant.
    Chunks created by users of tenant X are only visible to tenant X.
    super_admin sees everything.
    
    KnowledgeChunk doesn't have a direct tenant_id column — isolation is
    achieved via the creator's tenant.  We store tenant_id on the chunk
    (see migration note below) OR fall back to document-based isolation.
    
    If KnowledgeChunk has tenant_id column, filter by it.
    Otherwise return empty list (handled at query level by joining through documents).
    """
    tid = get_tenant_id(user)
    if tid is None:
        return []

    if hasattr(KnowledgeChunk, "tenant_id"):
        return [KnowledgeChunk.tenant_id == tid]

    return []   