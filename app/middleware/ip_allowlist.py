# app/middleware/ip_allowlist.py
"""
IP Allowlist Middleware
Caches DB rules for 60 s. Always exempts SSO callbacks and static paths.
"""
import time
import ipaddress
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import HTMLResponse
from app.config import settings

logger = logging.getLogger(__name__)

_cache: dict = {"ranges": [], "ts": 0.0}
_TTL = 60   # seconds

_EXEMPT = (
    "/auth/login", "/auth/register",
    "/auth/sso/",                    # SSO callbacks MUST be reachable
    "/static/", "/uploads/",
    "/manifest.json", "/sw.js",
    "/health",
)


async def _refresh(db) -> list[str]:
    from app.models import IPAllowlist
    from sqlalchemy import select
    rows = (await db.execute(
        select(IPAllowlist).where(IPAllowlist.is_active == True)
    )).scalars().all()
    return [r.ip_range for r in rows]


class IPAllowlistMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        if not settings.IP_ALLOWLIST_ENABLED:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(e) for e in _EXEMPT):
            return await call_next(request)

        # Refresh cache
        now = time.monotonic()
        if now - _cache["ts"] > _TTL:
            try:
                from app.database import AsyncSessionLocal
                async with AsyncSessionLocal() as db:
                    _cache["ranges"] = await _refresh(db)
                    _cache["ts"] = now
            except Exception as exc:
                logger.error(f"IP allowlist cache error: {exc}")
                # fail open — don't block on DB errors

        ranges = _cache["ranges"]
        if not ranges:
            return await call_next(request)   # no rules = allow all

        # Determine client IP (X-Forwarded-For aware)
        xff = request.headers.get("X-Forwarded-For", "")
        client_ip = xff.split(",")[0].strip() if xff else (
            request.client.host if request.client else "127.0.0.1"
        )

        try:
            addr = ipaddress.ip_address(client_ip)
            for rule in ranges:
                try:
                    if "/" in rule:
                        if addr in ipaddress.ip_network(rule, strict=False):
                            return await call_next(request)
                    elif addr == ipaddress.ip_address(rule):
                        return await call_next(request)
                except ValueError:
                    continue
        except ValueError:
            pass  # unparseable IP — fall through to block

        return HTMLResponse("""<!DOCTYPE html>
<html><head><title>Access Restricted — BOSS</title>
<style>body{font-family:sans-serif;background:#080c14;color:#e2e8f0;
  display:flex;align-items:center;justify-content:center;height:100vh;text-align:center}
h1{font-size:56px;margin:0;color:#ef4444}
p{color:#64748b;margin-top:8px}</style></head>
<body><div>
  <h1>403</h1>
  <p>Access is restricted to authorised networks.<br>
  Contact your IT administrator if you believe this is an error.</p>
</div></body></html>""", status_code=403)