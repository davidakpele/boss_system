# app/routers/push.py
"""
Web Push Notifications
  GET    /push/vapid-public-key     – VAPID public key for frontend
  POST   /push/subscribe            – save device subscription
  DELETE /push/subscribe            – remove device subscription
  POST   /push/test                 – send test notification to self
"""
import json
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.database import get_db
from app.models import PushSubscription, User
from app.auth import require_user
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/push", tags=["push"])

def _push(subscription_info: dict, payload: dict) -> bool:
    if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
        return False
    try:
        from pywebpush import webpush, WebPushException
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIMS_EMAIL}"},
        )
        return True
    except Exception as exc:
        logger.warning(f"Push send error: {exc}")
        return False

@router.get("/vapid-public-key")
async def vapid_key():
    return JSONResponse({"publicKey": settings.VAPID_PUBLIC_KEY})


@router.post("/subscribe")
async def subscribe(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    body = await request.json()
    endpoint = body.get("endpoint", "")
    keys     = body.get("keys", {})
    p256dh   = keys.get("p256dh", "")
    auth_key = keys.get("auth", "")

    if not all([endpoint, p256dh, auth_key]):
        return JSONResponse({"error": "Invalid subscription object"}, status_code=400)

    existing = (await db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    )).scalar_one_or_none()

    if existing:
        existing.user_id = current_user.id
        existing.p256dh  = p256dh
        existing.auth    = auth_key
    else:
        db.add(PushSubscription(
            user_id    = current_user.id,
            endpoint   = endpoint,
            p256dh     = p256dh,
            auth       = auth_key,
            user_agent = request.headers.get("user-agent", "")[:255],
        ))
    await db.commit()
    return JSONResponse({"status": "subscribed"})


@router.delete("/subscribe")
async def unsubscribe(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    body = await request.json()
    endpoint = body.get("endpoint", "")
    await db.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
    await db.commit()
    return JSONResponse({"status": "unsubscribed"})


@router.post("/test")
async def send_test(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    subs = (await db.execute(
        select(PushSubscription).where(PushSubscription.user_id == current_user.id)
    )).scalars().all()

    if not subs:
        return JSONResponse({"error": "No subscriptions found. Enable notifications first."}, status_code=400)

    payload = {
        "title": "BOSS System",
        "body":  f"🎉 Push is working, {current_user.full_name.split()[0]}!",
        "icon":  "/static/img/icon-192.png",
        "badge": "/static/img/icon-72.png",
        "url":   "/dashboard",
    }
    sent = sum(
        1 for s in subs
        if _push({"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}}, payload)
    )
    return JSONResponse({"sent": sent, "total": len(subs)})

async def notify_user(
    user_id: int,
    title: str,
    body: str,
    url: str = "/messages",
    db: AsyncSession = None,
):
    """Send a push notification to every device of a user."""
    if not settings.VAPID_PRIVATE_KEY or db is None:
        return
    subs = (await db.execute(
        select(PushSubscription).where(PushSubscription.user_id == user_id)
    )).scalars().all()
    payload = {
        "title": title, "body": body,
        "icon":  "/static/img/icon-192.png",
        "badge": "/static/img/icon-72.png",
        "url":   url,
    }
    for s in subs:
        _push({"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}}, payload)