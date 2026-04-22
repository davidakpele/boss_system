"""
app/permissions.py
──────────────────────────────────────────────────────────────────────────────
Role-Based Access Control (RBAC) — scoped by role, department, and action.

Roles (from UserRole enum):
  super_admin   – full access across all tenants
  admin         – full access within their tenant
  manager       – read/write for their department + read others
  staff         – read/write their own data + department read
  new_employee  – onboarding only; very limited access

Permission format:  "<resource>:<action>"
  resource:  documents | knowledge | messages | users | analytics |
             compliance | inventory | accounting | hr | tasks |
             meetings | announcements | audit | settings | tenants
  action:    read | write | delete | approve | export | manage

Usage:
    from app.permissions import require_permission, can

    # In a route:
    @router.get("/documents")
    async def list_docs(current_user: User = Depends(require_permission("documents:read"))):
        ...

    # Inline check:
    if not can(current_user, "documents:approve"):
        raise HTTPException(403)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole


# ── Permission matrix ─────────────────────────────────────────────────────────

# Maps UserRole → set of granted permissions
ROLE_PERMISSIONS: dict[str, set[str]] = {

    UserRole.super_admin: {
        # Everything
        "documents:read", "documents:write", "documents:delete", "documents:approve", "documents:export",
        "knowledge:read", "knowledge:write", "knowledge:delete",
        "messages:read", "messages:write", "messages:delete",
        "users:read", "users:write", "users:delete", "users:manage",
        "analytics:read", "analytics:export",
        "compliance:read", "compliance:write",
        "inventory:read", "inventory:write", "inventory:delete",
        "accounting:read", "accounting:write", "accounting:delete", "accounting:export",
        "hr:read", "hr:write", "hr:delete",
        "tasks:read", "tasks:write", "tasks:delete",
        "meetings:read", "meetings:write", "meetings:delete",
        "announcements:read", "announcements:write", "announcements:delete",
        "audit:read", "audit:export",
        "settings:read", "settings:write",
        "tenants:read", "tenants:write", "tenants:manage",
        "ai:use", "ai:manage",
        "platform:read", "platform:manage",
    },

    UserRole.admin: {
        "documents:read", "documents:write", "documents:delete", "documents:approve", "documents:export",
        "knowledge:read", "knowledge:write", "knowledge:delete",
        "messages:read", "messages:write", "messages:delete",
        "users:read", "users:write", "users:manage",
        "analytics:read", "analytics:export",
        "compliance:read", "compliance:write",
        "inventory:read", "inventory:write", "inventory:delete",
        "accounting:read", "accounting:write", "accounting:delete", "accounting:export",
        "hr:read", "hr:write", "hr:delete",
        "tasks:read", "tasks:write", "tasks:delete",
        "meetings:read", "meetings:write", "meetings:delete",
        "announcements:read", "announcements:write", "announcements:delete",
        "audit:read", "audit:export",
        "settings:read", "settings:write",
        "ai:use", "ai:manage",
        "platform:read",
    },

    UserRole.manager: {
        "documents:read", "documents:write", "documents:export",
        "knowledge:read", "knowledge:write",
        "messages:read", "messages:write", "messages:delete",
        "users:read",
        "analytics:read",
        "compliance:read",
        "inventory:read", "inventory:write",
        "accounting:read", "accounting:export",
        "hr:read", "hr:write",
        "tasks:read", "tasks:write", "tasks:delete",
        "meetings:read", "meetings:write", "meetings:delete",
        "announcements:read",
        "ai:use",
    },

    UserRole.staff: {
        "documents:read", "documents:write",
        "knowledge:read",
        "messages:read", "messages:write",
        "users:read",
        "inventory:read",
        "accounting:read",
        "hr:read",
        "tasks:read", "tasks:write",
        "meetings:read", "meetings:write",
        "announcements:read",
        "ai:use",
    },

    UserRole.new_employee: {
        "documents:read",
        "knowledge:read",
        "messages:read", "messages:write",
        "users:read",
        "meetings:read",
        "announcements:read",
        "ai:use",
    },
}


# ── Department-scoped resource guard ─────────────────────────────────────────
# These resources are additionally scoped: managers/staff can only write to
# their own department unless they have the :manage permission.

DEPARTMENT_SCOPED_RESOURCES = {
    "documents", "knowledge", "tasks", "inventory",
}


# ── Public helpers ────────────────────────────────────────────────────────────

def can(user: User, permission: str) -> bool:
    """
    Return True if user has the given permission.
    Handles None user gracefully (always False).
    """
    if user is None:
        return False
    role_perms = ROLE_PERMISSIONS.get(user.role, set())
    return permission in role_perms


def can_access_department(user: User, resource_department: Optional[str]) -> bool:
    """
    Return True if the user can access a resource belonging to `resource_department`.
    super_admin and admin can access all departments.
    manager/staff can only access their own department (or General/None).
    """
    if user.role in (UserRole.super_admin, UserRole.admin):
        return True
    if not resource_department or resource_department == "General":
        return True
    return (user.department or "").lower() == resource_department.lower()


def assert_permission(user: User, permission: str) -> None:
    """Raise HTTP 403 if user lacks permission."""
    if not can(user, permission):
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: {permission}",
        )


def assert_department_access(user: User, resource_department: Optional[str]) -> None:
    """Raise HTTP 403 if user can't access the given department's resource."""
    if not can_access_department(user, resource_department):
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: you don't have access to the '{resource_department}' department",
        )


# ── FastAPI dependency factories ──────────────────────────────────────────────

def require_permission(permission: str):
    """
    FastAPI dependency factory.
    Usage:  Depends(require_permission("documents:approve"))
    """
    from app.auth import require_user

    async def _check(current_user: User = Depends(require_user)) -> User:
        assert_permission(current_user, permission)
        return current_user

    return _check


def require_any_permission(*permissions: str):
    """User must have at least one of the listed permissions."""
    from app.auth import require_user

    async def _check(current_user: User = Depends(require_user)) -> User:
        if not any(can(current_user, p) for p in permissions):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: requires one of {list(permissions)}",
            )
        return current_user

    return _check


def require_same_tenant(target_tenant_id: int):
    """Ensure the acting user belongs to the same tenant as the resource."""
    from app.auth import require_user

    async def _check(current_user: User = Depends(require_user)) -> User:
        if current_user.role == UserRole.super_admin:
            return current_user
        if current_user.tenant_id != target_tenant_id:
            raise HTTPException(status_code=403, detail="Cross-tenant access denied")
        return current_user

    return _check