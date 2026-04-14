# app/routers/calls.py
"""
Call management routes:
  POST /calls/start          — log call start, return call_uuid
  POST /calls/{uuid}/answer  — mark participant as answered
  POST /calls/{uuid}/reject  — mark participant as rejected
  POST /calls/{uuid}/end     — end call (1:1 kills it; conference removes participant)
  POST /calls/{uuid}/missed  — scheduler marks unanswered calls missed after 45s
  GET  /calls/history        — call history for current user (answered + missed)
  GET  /calls/missed         — only missed/rejected calls (for badge count)
"""

import uuid as _uuid
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from app.database import get_db, AsyncSessionLocal
from app.models import CallRecord, CallParticipant, User, Channel, ChannelMember
from app.auth import require_user
from app.services.websocket_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calls", tags=["calls"])


@router.post("/start")
async def start_call(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    body = await request.json()
    channel_id = body.get("channel_id")
    call_type  = body.get("call_type", "audio")   # audio | video
    target_ids = body.get("target_user_ids", [])  

    if not channel_id:
        return JSONResponse({"error": "channel_id required"}, status_code=400)

    call_uuid = str(_uuid.uuid4())

    call = CallRecord(
        call_uuid   = call_uuid,
        channel_id  = channel_id,
        call_type   = call_type,
        status      = "ongoing",
        is_conference = len(target_ids) > 1,
    )
    db.add(call)
    await db.flush()

    db.add(CallParticipant(
        call_id   = call.id,
        user_id   = current_user.id,
        role      = "caller",
        status    = "answered",
        joined_at = datetime.utcnow(),
    ))
    for uid in target_ids:
        db.add(CallParticipant(
            call_id = call.id,
            user_id = int(uid),
            role    = "callee",
            status  = "ringing",
        ))

    await db.commit()

    return JSONResponse({
        "call_uuid":    call_uuid,
        "call_id":      call.id,
        "call_type":    call_type,
        "is_conference": call.is_conference,
    })


@router.post("/{call_uuid}/answer")
async def answer_call(
    call_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    call = (await db.execute(
        select(CallRecord).where(CallRecord.call_uuid == call_uuid)
    )).scalar_one_or_none()
    if not call:
        raise HTTPException(404)

    participant = (await db.execute(
        select(CallParticipant).where(
            CallParticipant.call_id == call.id,
            CallParticipant.user_id == current_user.id,
        )
    )).scalar_one_or_none()

    if not participant:
        participant = CallParticipant(
            call_id = call.id,
            user_id = current_user.id,
            role    = "callee",
        )
        db.add(participant)

    participant.status    = "answered"
    participant.joined_at = datetime.utcnow()

    if not call.answered_at:
        call.answered_at = datetime.utcnow()
        call.status      = "answered"

    await db.commit()
    return JSONResponse({"status": "answered"})


@router.post("/{call_uuid}/reject")
async def reject_call(
    call_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    call = (await db.execute(
        select(CallRecord).where(CallRecord.call_uuid == call_uuid)
    )).scalar_one_or_none()
    if not call:
        raise HTTPException(404)

    participant = (await db.execute(
        select(CallParticipant).where(
            CallParticipant.call_id == call.id,
            CallParticipant.user_id == current_user.id,
        )
    )).scalar_one_or_none()

    if participant:
        participant.status  = "rejected"
        participant.left_at = datetime.utcnow()

    all_participants = (await db.execute(
        select(CallParticipant).where(CallParticipant.call_id == call.id)
    )).scalars().all()

    callees = [p for p in all_participants if p.role == "callee"]
    all_rejected = all(p.status in ("rejected", "missed") for p in callees)

    if all_rejected and not call.is_conference:
        call.status   = "rejected"
        call.ended_at = datetime.utcnow()

    await db.commit()
    return JSONResponse({"status": "rejected"})

@router.post("/{call_uuid}/end")
async def end_call(
    call_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    call = (await db.execute(
        select(CallRecord).where(CallRecord.call_uuid == call_uuid)
    )).scalar_one_or_none()
    if not call:
        raise HTTPException(404)

    now = datetime.utcnow()
    participant = (await db.execute(
        select(CallParticipant).where(
            CallParticipant.call_id == call.id,
            CallParticipant.user_id == current_user.id,
        )
    )).scalar_one_or_none()

    if participant:
        participant.status  = "left"
        participant.left_at = now
    active = (await db.execute(
        select(func.count(CallParticipant.id)).where(
            CallParticipant.call_id == call.id,
            CallParticipant.status  == "answered",
            CallParticipant.user_id != current_user.id,
        )
    )).scalar() or 0

    is_conference = call.is_conference

    if is_conference and active >= 2:
        action = "left"
    else:
        call.status   = "ended"
        call.ended_at = now
        if call.answered_at:
            call.duration_s = int((now - call.answered_at.replace(tzinfo=None)).total_seconds())
        action = "ended"

    await db.commit()

    return JSONResponse({
        "action":          action,
        "active_remaining": active,
        "call_uuid":       call_uuid,
    })

@router.post("/{call_uuid}/missed")
async def mark_missed(
    call_uuid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    call = (await db.execute(
        select(CallRecord).where(CallRecord.call_uuid == call_uuid)
    )).scalar_one_or_none()
    if not call or call.status != "ongoing":
        return JSONResponse({"status": "no_action"})

    ringing = (await db.execute(
        select(CallParticipant).where(
            CallParticipant.call_id == call.id,
            CallParticipant.status  == "ringing",
        )
    )).scalars().all()

    for p in ringing:
        p.status  = "missed"
        p.left_at = datetime.utcnow()

    call.status   = "missed"
    call.ended_at = datetime.utcnow()
    await db.commit()

    return JSONResponse({"status": "marked_missed", "count": len(ringing)})


@router.get("/history")
async def call_history(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """All calls this user was part of, newest first."""
    rows = (await db.execute(
        select(CallRecord, CallParticipant)
        .join(CallParticipant, CallParticipant.call_id == CallRecord.id)
        .where(CallParticipant.user_id == current_user.id)
        .order_by(CallRecord.started_at.desc())
        .limit(limit)
    )).all()

    results = []
    for call, participant in rows:
        # Get other participants for display
        others = (await db.execute(
            select(User.full_name, User.avatar_color, CallParticipant.role)
            .join(CallParticipant, CallParticipant.user_id == User.id)
            .where(
                CallParticipant.call_id  == call.id,
                CallParticipant.user_id  != current_user.id,
            )
        )).all()

        duration = None
        if call.duration_s is not None:
            m = call.duration_s // 60
            s = call.duration_s % 60
            duration = f"{m}:{str(s).zfill(2)}"

        results.append({
            "call_uuid":     call.call_uuid,
            "call_type":     call.call_type,
            "status":        call.status,
            "my_status":     participant.status,
            "is_conference": call.is_conference,
            "duration":      duration,
            "started_at":    call.started_at.isoformat() if call.started_at else "",
            "ended_at":      call.ended_at.isoformat()   if call.ended_at   else "",
            "participants":  [{"name": n, "color": c, "role": r} for n, c, r in others],
        })

    return JSONResponse(results)


@router.get("/missed/count")
async def missed_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Badge count for missed/rejected calls."""
    # Missed since last login or last 7 days
    since = datetime.utcnow() - timedelta(days=7)
    count = (await db.execute(
        select(func.count(CallParticipant.id))
        .join(CallRecord, CallParticipant.call_id == CallRecord.id)
        .where(
            CallParticipant.user_id == current_user.id,
            CallParticipant.status.in_(["missed", "rejected"]),
            CallRecord.started_at >= since,
        )
    )).scalar() or 0
    return JSONResponse({"count": count})