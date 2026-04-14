# app/middleware/rate_limiter.py
"""
12. Rate Limiting Middleware
Uses in-memory sliding window (no Redis needed).
Falls back gracefully — never crashes the app.
"""
import time
import logging
from collections import defaultdict
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

RATE_RULES = {
    "/auth/login":           (10,  60), 
    "/auth/register":        (5,   60),
    "/whatsapp/send":        (30,  60),
    "/ai/writing/assist":    (20,  60),
    "/ai/documents":         (20,  60),
    "/ai/sentiment":         (10,  60),
    "/ai/meeting":           (10,  60),
    "/bcc/accounting/ai-parse": (30, 60),
    "/bcc/hr/applications":  (20,  60),
    "/search":               (60,  60),
    "/api/":                 (100, 60),
}

BLOCKED_DURATION = 300 


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter using in-memory storage.
    Key: IP address + path prefix
    """

    def __init__(self, app):
        super().__init__(app)
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._blocked: dict[str, float] = {} 

    def _get_rule(self, path: str, method: str):
        """Find the most specific matching rule."""
        for prefix, rule in RATE_RULES.items():
            if path.startswith(prefix):
                return rule
        return None

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        path   = request.url.path
        method = request.method
        if path.startswith(("/static/", "/uploads/", "/sw.js", "/manifest.json")):
            return await call_next(request)

        rule = self._get_rule(path, method)
        if rule is None:
            return await call_next(request)

        max_req, window_s = rule
        ip  = self._get_client_ip(request)
        key = f"{ip}:{path.split('/')[1]}"

        now = time.time()
        unblock_at = self._blocked.get(key, 0)
        if now < unblock_at:
            remaining = int(unblock_at - now)
            return JSONResponse(
                status_code=429,
                content={
                    "error":   "Too many requests",
                    "detail":  f"Rate limit exceeded. Try again in {remaining}s.",
                    "retry_after": remaining,
                }
            )

        window = self._windows[key]
        self._windows[key] = [t for t in window if now - t < window_s]

        if len(self._windows[key]) >= max_req:
            self._blocked[key] = now + BLOCKED_DURATION
            logger.warning(f"Rate limit exceeded: {ip} on {path} — blocked for {BLOCKED_DURATION}s")
            return JSONResponse(
                status_code=429,
                content={
                    "error":   "Too many requests",
                    "detail":  f"Rate limit exceeded. Blocked for {BLOCKED_DURATION // 60} minutes.",
                    "retry_after": BLOCKED_DURATION,
                }
            )
        self._windows[key].append(now)
        response = await call_next(request)
        remaining = max_req - len(self._windows[key])
        response.headers["X-RateLimit-Limit"]     = str(max_req)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        response.headers["X-RateLimit-Window"]    = str(window_s)
        return response