"""
app/services/tenant_service.py
──────────────────────────────────────────────────────────────────────────────
Helpers that auto-stamp tenant_id on newly created records so data isolation
is enforced consistently without having to remember it in every route.
"""

from __future__ import annotations
from typing import Optional
from app.models import User, UserRole


def stamp_tenant(obj, user: User) -> None:
    """
    Set obj.tenant_id = user.tenant_id if:
      - obj has a tenant_id attribute, AND
      - user is not a super_admin (super_admin records are untenanted)
    Call this after constructing any new DB model instance.

    Example:
        doc = Document(title=..., ...)
        stamp_tenant(doc, current_user)
        db.add(doc)
    """
    if not hasattr(obj, "tenant_id"):
        return
    if user.role == UserRole.super_admin:
        return   # super_admin data is not tenant-scoped
    obj.tenant_id = user.tenant_id


def propagate_tenant(user: User, **kwargs) -> dict:
    """
    Return kwargs with tenant_id injected.
    Useful for Model(**propagate_tenant(user, title=..., content=...))
    """
    if user.role != UserRole.super_admin and user.tenant_id is not None:
        kwargs["tenant_id"] = user.tenant_id
    return kwargs