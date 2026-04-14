# src/app/routers/messages.py 
from datetime import datetime, timezone, timedelta
from http.client import HTTPException
import os
import re
import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect, Form, UploadFile, File, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, or_

from app.database import get_db, AsyncSessionLocal
from app.models import Channel, ChannelMember, Message, User, KnowledgeChunk
from app.models import MessageReaction, MessageReadReceipt, Mention
from app.auth import require_user
from app.services.websocket_manager import manager
from app.services.ai_service import ai_service
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["messages"])
templates = Jinja2Templates(directory="app/templates")

DEPARTMENTS = ["HR", "Sales", "Technology", "Finance", "Operations", "Legal", "Marketing", "Management", "General"]

MAX_FILE_SIZE   = 20 * 1024 * 1024
MAX_VOICE_SIZE  = 10 * 1024 * 1024

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv",
    "py", "js", "ts", "html", "json", "md",
    "zip", "rar", "7z",
    "mp3", "wav", "mp4", "mov", "avi",
    "webm", "ogg",
}

STATIC_UPLOAD_DIR = os.path.join("app", "static", "uploads", "messages")
VOICE_UPLOAD_DIR  = os.path.join("app", "static", "uploads", "voice")


# ── PAGES ──────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def messages_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    channels_q = await db.execute(
        select(Channel)
        .join(ChannelMember, and_(
            ChannelMember.channel_id == Channel.id,
            ChannelMember.user_id == current_user.id,
        ))
        .where(Channel.channel_type == "department")
        .order_by(Channel.name)
    )
    channels = channels_q.scalars().all()

    all_users = (await db.execute(
        select(User).where(User.id != current_user.id).order_by(User.full_name)
    )).scalars().all()

    all_channels = (await db.execute(
        select(Channel).where(Channel.channel_type == "department").order_by(Channel.name)
    )).scalars().all()

    member_channel_ids = {ch.id for ch in channels}

    mention_count = (await db.execute(
        select(func.count()).where(
            and_(Mention.mentioned_user_id == current_user.id, Mention.is_read == False)
        )
    )).scalar() or 0

    return templates.TemplateResponse(
        request=request,
        name="messages/index.html",
        context={
            "user": current_user,
            "current_user": current_user,
            "channels": channels,
            "all_users": all_users,
            "all_channels": all_channels,
            "member_channel_ids": member_channel_ids,
            "departments": DEPARTMENTS,
            "page": "messages",
            "mention_count": mention_count,
        }
    )


# ── HISTORY ────────────────────────────────────────────────────────────────────

@router.get("/channel/{channel_id}/history")
async def get_channel_history(
    channel_id: int,
    thread_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    where_clauses = [Message.channel_id == channel_id]
    if thread_id:
        # Thread replies for a specific parent
        where_clauses.append(Message.thread_id == thread_id)
        where_clauses.append(Message.is_thread_reply == True)
    else:
        # Top-level messages only — exclude thread replies
        # Use explicit False check + handle NULL (older rows may have NULL)
        where_clauses.append(
            or_(Message.is_thread_reply == False, Message.is_thread_reply == None)
        )

    stmt = (
        select(Message, User.full_name, User.avatar_color)
        .join(User, Message.sender_id == User.id)
        .where(and_(*where_clauses))
        .order_by(Message.created_at.asc())
        .limit(200)
    )
    result = await db.execute(stmt)
    messages = []
    for msg, name, color in result.all():
        m = _serialize_message(msg, name, color)
        m["reactions"] = await _get_reactions(db, msg.id, current_user.id)
        messages.append(m)
    return JSONResponse(messages)


@router.get("/dm/{other_user_id}/init")
async def init_dm(
    other_user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    channel = await _get_or_create_dm(db, current_user.id, other_user_id)

    stmt = (
        select(Message, User.full_name, User.avatar_color)
        .join(User, Message.sender_id == User.id)
        .where(
            Message.channel_id == channel.id,
            or_(Message.is_thread_reply == False, Message.is_thread_reply == None),
        )
        .order_by(Message.created_at.asc())
        .limit(200)
    )
    result = await db.execute(stmt)
    messages = []
    for msg, name, color in result.all():
        m = _serialize_message(msg, name, color)
        m["reactions"] = await _get_reactions(db, msg.id, current_user.id)
        messages.append(m)

    return JSONResponse({"channel_id": channel.id, "messages": messages})


async def _get_reactions(db: AsyncSession, message_id: int, current_user_id: int) -> list:
    rows = (await db.execute(
        select(MessageReaction.emoji, func.count().label("cnt"))
        .where(MessageReaction.message_id == message_id)
        .group_by(MessageReaction.emoji)
    )).all()

    agg: dict[str, dict] = {}
    for emoji, cnt in rows:
        agg[emoji] = {"emoji": emoji, "count": cnt, "reacted_by_me": False}

    my_rows = (await db.execute(
        select(MessageReaction.emoji)
        .where(MessageReaction.message_id == message_id, MessageReaction.user_id == current_user_id)
    )).scalars().all()
    for emoji in my_rows:
        if emoji in agg:
            agg[emoji]["reacted_by_me"] = True

    return list(agg.values())


def _serialize_message(msg: Message, sender_name: str, avatar_color: str) -> dict:
    return {
        "id": msg.id,
        "content": msg.content or "",
        "sender_id": msg.sender_id,
        "sender_name": sender_name,
        "avatar_color": avatar_color,
        "created_at": msg.created_at.isoformat() if msg.created_at else "",
        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
        "message_type": msg.message_type or "text",
        "is_deleted": bool(msg.is_deleted),
        "is_ai_extracted": bool(msg.is_ai_extracted),
        "reply_to_id": msg.reply_to_id,
        "reply_to_sender": msg.reply_to_sender,
        "reply_to_content": msg.reply_to_content,
        "file_url": msg.file_url,
        "file_name": msg.file_name,
        "file_size": msg.file_size,
        # FIX: include voice_duration so the player shows correct time
        "voice_duration": getattr(msg, "voice_duration", None),
        "thread_id": getattr(msg, "thread_id", None),
        "thread_count": getattr(msg, "thread_count", 0) or 0,
        "is_thread_reply": bool(getattr(msg, "is_thread_reply", False)),
        "reactions": [],
    }


# ── DM HELPER ──────────────────────────────────────────────────────────────────

async def _get_or_create_dm(db: AsyncSession, user_a: int, user_b: int) -> Channel:
    dm_name = f"dm_{min(user_a, user_b)}_{max(user_a, user_b)}"
    existing = (await db.execute(
        select(Channel).where(Channel.name == dm_name, Channel.channel_type == "direct")
    )).scalar_one_or_none()
    if existing:
        return existing

    channel = Channel(name=dm_name, channel_type="direct", created_by=user_a)
    db.add(channel)
    await db.flush()
    db.add(ChannelMember(channel_id=channel.id, user_id=user_a))
    db.add(ChannelMember(channel_id=channel.id, user_id=user_b))
    await db.commit()
    await db.refresh(channel)
    return channel


# ── CHANNEL MANAGEMENT ─────────────────────────────────────────────────────────

@router.post("/channel/create")
async def create_channel(
    name: str = Form(...),
    description: str = Form(""),
    departments: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    dept_list = [d.strip() for d in departments.split(",") if d.strip()]
    channel = Channel(
        name=name, description=description, department=",".join(dept_list),
        channel_type="department", created_by=current_user.id,
    )
    db.add(channel)
    await db.flush()
    db.add(ChannelMember(channel_id=channel.id, user_id=current_user.id))
    if dept_list:
        dept_users = (await db.execute(
            select(User).where(User.department.in_(dept_list), User.id != current_user.id)
        )).scalars().all()
        for u in dept_users:
            db.add(ChannelMember(channel_id=channel.id, user_id=u.id))
    await db.commit()
    return JSONResponse({"id": channel.id, "name": channel.name})


@router.post("/channel/{channel_id}/join")
async def join_channel(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    existing = (await db.execute(
        select(ChannelMember).where(
            and_(ChannelMember.channel_id == channel_id, ChannelMember.user_id == current_user.id)
        )
    )).scalar_one_or_none()
    if not existing:
        db.add(ChannelMember(channel_id=channel_id, user_id=current_user.id))
        await db.commit()
    return JSONResponse({"status": "ok"})


@router.post("/channel/{channel_id}/update")
async def update_channel(
    channel_id: int,
    name: str = Form(...),
    description: str = Form(""),
    departments: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    channel = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not channel:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if channel.created_by != current_user.id and current_user.role.value not in ("super_admin", "admin"):
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    dept_list = [d.strip() for d in departments.split(",") if d.strip()]
    channel.name = name
    channel.description = description
    channel.department = ",".join(dept_list)

    await db.execute(
        ChannelMember.__table__.delete().where(
            and_(ChannelMember.channel_id == channel_id, ChannelMember.user_id != current_user.id)
        )
    )
    if dept_list:
        dept_users = (await db.execute(
            select(User).where(User.department.in_(dept_list), User.id != current_user.id)
        )).scalars().all()
        for u in dept_users:
            db.add(ChannelMember(channel_id=channel_id, user_id=u.id))
    await db.commit()
    return JSONResponse({"status": "updated"})


# ── FILE UPLOAD ────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_file(
    channel_id: int = Form(...),
    file: UploadFile = File(...),
    reply_to_id: int | None = Form(None),
    reply_to_sender: str | None = Form(None),
    reply_to_content: str | None = Form(None),
    thread_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse({"error": f"File type '.{ext}' not allowed"}, status_code=400)

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        return JSONResponse({"error": "File too large (max 20 MB)"}, status_code=400)

    os.makedirs(STATIC_UPLOAD_DIR, exist_ok=True)
    safe_stem = Path(file.filename or "file").stem[:40]
    unique_name = f"{uuid.uuid4().hex}_{safe_stem}.{ext}"
    dest = os.path.join(STATIC_UPLOAD_DIR, unique_name)
    with open(dest, "wb") as f:
        f.write(data)

    file_url = f"/static/uploads/messages/{unique_name}"

    async with AsyncSessionLocal() as sess:
        msg = Message(
            channel_id=channel_id,
            sender_id=current_user.id,
            content=None,
            message_type="file",
            file_url=file_url,
            file_name=file.filename,
            file_size=len(data),
            reply_to_id=reply_to_id,
            reply_to_sender=reply_to_sender,
            reply_to_content=reply_to_content,
            thread_id=thread_id,
            is_thread_reply=thread_id is not None,
            is_deleted=False,
            is_ai_extracted=False,
        )
        sess.add(msg)
        await sess.commit()
        await sess.refresh(msg)

        if thread_id:
            parent = (await sess.execute(select(Message).where(Message.id == thread_id))).scalar_one_or_none()
            if parent:
                parent.thread_count = (parent.thread_count or 0) + 1
                await sess.commit()

        payload = {
            "type": "message",
            **_serialize_message(msg, current_user.full_name, current_user.avatar_color),
        }
        await manager.broadcast_to_channel(channel_id, payload)

    return JSONResponse({"status": "ok", "file_url": file_url})


# ── VOICE NOTE UPLOAD ──────────────────────────────────────────────────────────

@router.post("/voice")
async def upload_voice(
    channel_id: int = Form(...),
    file: UploadFile = File(...),
    duration: int = Form(0),
    thread_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    data = await file.read()
    if len(data) > MAX_VOICE_SIZE:
        return JSONResponse({"error": "Voice note too large (max 10 MB)"}, status_code=400)

    os.makedirs(VOICE_UPLOAD_DIR, exist_ok=True)
    ext = Path(file.filename or "voice.webm").suffix.lstrip(".").lower() or "webm"
    unique_name = f"voice_{uuid.uuid4().hex}.{ext}"
    dest = os.path.join(VOICE_UPLOAD_DIR, unique_name)
    with open(dest, "wb") as f:
        f.write(data)

    file_url = f"/static/uploads/voice/{unique_name}"

    async with AsyncSessionLocal() as sess:
        msg = Message(
            channel_id=channel_id,
            sender_id=current_user.id,
            content=f"Voice note ({duration}s)" if duration else "Voice note",
            message_type="voice",
            file_url=file_url,
            file_name=unique_name,
            file_size=len(data),
            voice_duration=duration,   # FIX: store duration in DB
            thread_id=thread_id,
            is_thread_reply=thread_id is not None,
            is_deleted=False,
            is_ai_extracted=False,
        )
        sess.add(msg)
        await sess.commit()
        await sess.refresh(msg)

        payload = {
            "type": "message",
            **_serialize_message(msg, current_user.full_name, current_user.avatar_color),
            "voice_duration": duration,
        }
        await manager.broadcast_to_channel(channel_id, payload)

    return JSONResponse({"status": "ok", "file_url": file_url})


# ── REACTIONS ─────────────────────────────────────────────────────────────────

@router.post("/{message_id}/react")
async def toggle_reaction(
    message_id: int,
    emoji: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    existing = (await db.execute(
        select(MessageReaction).where(
            MessageReaction.message_id == message_id,
            MessageReaction.user_id == current_user.id,
            MessageReaction.emoji == emoji,
        )
    )).scalar_one_or_none()

    msg = (await db.execute(select(Message).where(Message.id == message_id))).scalar_one_or_none()
    if not msg:
        return JSONResponse({"error": "Not found"}, status_code=404)

    if existing:
        await db.delete(existing)
        action = "removed"
    else:
        db.add(MessageReaction(message_id=message_id, user_id=current_user.id, emoji=emoji))
        action = "added"
    await db.commit()

    reactions = await _get_reactions(db, message_id, current_user.id)
    payload = {
        "type": "reaction",
        "message_id": message_id,
        "reactions": reactions,
        "action": action,
        "emoji": emoji,
        "user_id": current_user.id,
    }
    await manager.broadcast_to_channel(msg.channel_id, payload)
    return JSONResponse({"status": action, "reactions": reactions})


# ── READ RECEIPTS ─────────────────────────────────────────────────────────────

@router.get("/{message_id}/readers")
async def get_readers(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    rows = (await db.execute(
        select(User.full_name, MessageReadReceipt.read_at)
        .join(User, MessageReadReceipt.user_id == User.id)
        .where(MessageReadReceipt.message_id == message_id)
        .order_by(MessageReadReceipt.read_at.asc())
    )).all()
    return JSONResponse([{"name": r.full_name, "read_at": r.read_at.isoformat()} for r in rows])


# ── SEARCH ────────────────────────────────────────────────────────────────────

@router.get("/search")
async def search_messages(
    channel_id: int = Query(...),
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    pattern = f"%{q}%"
    stmt = (
        select(Message, User.full_name, User.avatar_color)
        .join(User, Message.sender_id == User.id)
        .where(
            Message.channel_id == channel_id,
            Message.content.ilike(pattern),
            Message.is_deleted == False,
        )
        .order_by(Message.created_at.asc())
        .limit(50)
    )
    result = await db.execute(stmt)
    messages = []
    for msg, name, color in result.all():
        m = _serialize_message(msg, name, color)
        m["reactions"] = []
        messages.append(m)
    return JSONResponse({"results": messages, "query": q})


# ── MENTIONS ─────────────────────────────────────────────────────────────────

@router.get("/mentions")
async def get_mentions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    rows = (await db.execute(
        select(Mention, Message, User.full_name.label("sender_name"))
        .join(Message, Mention.message_id == Message.id)
        .join(User, Mention.sender_id == User.id)
        .where(Mention.mentioned_user_id == current_user.id)
        .order_by(Mention.created_at.desc())
        .limit(30)
    )).all()

    results = []
    for mention, msg, sender_name in rows:
        results.append({
            "id": mention.id,
            "message_id": mention.message_id,
            "channel_id": mention.channel_id,
            "sender_name": sender_name,
            "content": msg.content or "",
            "is_read": mention.is_read,
            "created_at": mention.created_at.isoformat(),
        })
    return JSONResponse(results)


@router.post("/mentions/read-all")
async def mark_mentions_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    await db.execute(
        Mention.__table__.update()
        .where(Mention.mentioned_user_id == current_user.id)
        .values(is_read=True)
    )
    await db.commit()
    return JSONResponse({"status": "ok"})


# ── DELETE MESSAGE ─────────────────────────────────────────────────────────────

@router.post("/{message_id}/delete")
async def delete_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    msg = (await db.execute(select(Message).where(Message.id == message_id))).scalar_one_or_none()
    if not msg:
        return JSONResponse({"error": "Not found"}, status_code=404)

    is_admin = current_user.role.value in ("super_admin", "admin")
    if msg.sender_id != current_user.id and not is_admin:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    msg.is_deleted = True
    msg.content = None
    await db.commit()

    await manager.broadcast_to_channel(msg.channel_id, {
        "type": "message_deleted",
        "message_id": message_id,
    })
    return JSONResponse({"status": "deleted"})


# ── MENTION HELPER ─────────────────────────────────────────────────────────────

async def _process_mentions(content: str, message_id: int, sender_id: int, channel_id: int, sess: AsyncSession):
    """Parse @name mentions, store them, push WS notifications."""
    # Match @FirstName LastName style (up to 40 chars)
    pattern = re.compile(r'@([A-Za-z][^\s@][^@\n]{0,38}?)(?=\s|$|[^\w])')
    raw_names = pattern.findall(content)
    if not raw_names:
        return

    for raw in raw_names:
        name = raw.strip()
        if not name:
            continue

        user = (await sess.execute(
            select(User).where(func.lower(User.full_name) == name.lower())
        )).scalar_one_or_none()

        if not user or user.id == sender_id:
            continue

        # Avoid duplicate mentions for same message+user
        existing_mention = (await sess.execute(
            select(Mention).where(
                Mention.message_id == message_id,
                Mention.mentioned_user_id == user.id,
            )
        )).scalar_one_or_none()
        if existing_mention:
            continue

        sess.add(Mention(
            message_id=message_id,
            sender_id=sender_id,
            mentioned_user_id=user.id,
            channel_id=channel_id,
            is_read=False,
        ))

        sender = (await sess.execute(select(User).where(User.id == sender_id))).scalar_one_or_none()
        # Send to all active connections for the mentioned user
        await manager.send_to_user(user.id, {
            "type": "mention",
            "channel_id": channel_id,
            "message_id": message_id,
            "sender_name": sender.full_name if sender else "Someone",
            "content": content[:120],
        })

    await sess.commit()


# ── WEBSOCKET ──────────────────────────────────────────────────────────────────

@router.websocket("/ws/{channel_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    channel_id: int,
    token: str = None,
):
    from jose import jwt, JWTError
    from app.config import settings as cfg

    user = None
    try:
        if token:
            payload = jwt.decode(token, cfg.SECRET_KEY, algorithms=[cfg.ALGORITHM])
            user_id = int(payload.get("sub"))
            async with AsyncSessionLocal() as sess:
                res = await sess.execute(select(User).where(User.id == user_id))
                user = res.scalar_one_or_none()
    except Exception as e:
        logger.error(f"WS auth error: {e}")

    if not user:
        await websocket.accept()
        await websocket.close(code=4001)
        return

    await manager.connect_to_channel(websocket, channel_id, user.id, user.full_name)
    await manager.broadcast_to_channel(channel_id, {
        "type": "user_joined",
        "user_id": user.id,
        "user_name": user.full_name,
    }, exclude_user=user.id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "message":
                content = data.get("content", "").strip()
                if not content:
                    continue

                thread_id = data.get("thread_id")

                async with AsyncSessionLocal() as sess:
                    msg = Message(
                        channel_id=channel_id,
                        sender_id=user.id,
                        content=content,
                        message_type="text",
                        reply_to_id=data.get("reply_to_id"),
                        reply_to_sender=data.get("reply_to_sender"),
                        reply_to_content=data.get("reply_to_content"),
                        thread_id=thread_id,
                        is_thread_reply=thread_id is not None,
                        is_deleted=False,
                        is_ai_extracted=False,
                        file_url=None,
                        file_name=None,
                        file_size=None,
                    )
                    sess.add(msg)
                    await sess.commit()
                    await sess.refresh(msg)

                    if thread_id:
                        parent = (await sess.execute(
                            select(Message).where(Message.id == thread_id)
                        )).scalar_one_or_none()
                        if parent:
                            parent.thread_count = (parent.thread_count or 0) + 1
                            await sess.commit()

                    serialized = _serialize_message(msg, user.full_name, user.avatar_color)
                    payload_out = {"type": "message", **serialized}
                    await manager.broadcast_to_channel(channel_id, payload_out)

                    # Process @mentions
                    await _process_mentions(content, msg.id, user.id, channel_id, sess)

                # Knowledge extraction (non-blocking, best-effort)
                try:
                    async with AsyncSessionLocal() as ai_sess:
                        knowledge = await ai_service.extract_knowledge_from_message(content, ai_sess)
                        if knowledge:
                            ai_sess.add(KnowledgeChunk(
                                source_type="message",
                                content=content,
                                summary=knowledge,
                                department=user.department,
                            ))
                            await ai_sess.commit()
                except Exception as e:
                    logger.error(f"Knowledge extraction error: {e}")

            elif msg_type == "typing":
                await manager.broadcast_to_channel(channel_id, {
                    "type": "typing",
                    "user_id": user.id,
                    "user_name": user.full_name,
                }, exclude_user=user.id)

            elif msg_type == "delete":
                message_id = data.get("message_id")
                if message_id:
                    await manager.broadcast_to_channel(channel_id, {
                        "type": "message_deleted",
                        "message_id": message_id,
                    }, exclude_user=user.id)

            elif msg_type == "read":
                # FIX: handle read receipt entirely in WS (no HTTP route needed from frontend)
                message_id = data.get("message_id")
                if message_id:
                    async with AsyncSessionLocal() as sess:
                        existing = (await sess.execute(
                            select(MessageReadReceipt).where(
                                MessageReadReceipt.message_id == message_id,
                                MessageReadReceipt.user_id == user.id,
                            )
                        )).scalar_one_or_none()
                        if not existing:
                            sess.add(MessageReadReceipt(message_id=message_id, user_id=user.id))
                            await sess.commit()
                    # Broadcast receipt to others in channel (sender sees it on others' screens)
                    await manager.broadcast_to_channel(channel_id, {
                        "type": "read_receipt",
                        "message_id": message_id,
                        "user_id": user.id,
                        "user_name": user.full_name,
                    }, exclude_user=user.id)

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "call_start":
                await manager.broadcast_to_channel(channel_id, {
                    "type":         "call_start",
                    "call_type":    data.get("call_type", "audio"),
                    "call_uuid":    data.get("call_uuid", ""),
                    "caller_id":    user.id,
                    "caller_name":  user.full_name,
                    "caller_color": user.avatar_color,
                    "channel_id":   channel_id,
                    "target_ids":   data.get("target_ids", []),
                }, exclude_user=user.id)
 
            elif msg_type == "call_offer":
                target_user_id = data.get("target_user_id")
                if target_user_id:
                    await manager.send_to_user(int(target_user_id), {
                        "type":          "call_offer",
                        "offer":         data.get("offer"),
                        "from_user_id":  user.id,
                        "from_user_name":user.full_name,
                        "call_uuid":     data.get("call_uuid", ""),
                        "channel_id":    channel_id,
                    })
 
            elif msg_type == "call_answer":
                target_user_id = data.get("target_user_id")
                if target_user_id:
                    await manager.send_to_user(int(target_user_id), {
                        "type":          "call_answer",
                        "answer":        data.get("answer"),
                        "from_user_id":  user.id,
                        "from_user_name":user.full_name,
                        "call_uuid":     data.get("call_uuid", ""),
                    })
 
            elif msg_type == "ice_candidate":
                target_user_id = data.get("target_user_id")
                if target_user_id:
                    await manager.send_to_user(int(target_user_id), {
                        "type":          "ice_candidate",
                        "candidate":     data.get("candidate"),
                        "from_user_id":  user.id,
                        "call_uuid":     data.get("call_uuid", ""),
                    })
 
            elif msg_type == "call_end":
                call_uuid = data.get("call_uuid", "")
                is_conference = data.get("is_conference", False)
                active_peers = [
                    uid for uid in manager.get_online_users(channel_id)
                    if uid != user.id
                ]
 
                if is_conference and len(active_peers) >= 2:
                    await manager.broadcast_to_channel(channel_id, {
                        "type":       "call_participant_left",
                        "user_id":    user.id,
                        "user_name":  user.full_name,
                        "call_uuid":  call_uuid,
                        "remaining":  len(active_peers),
                    }, exclude_user=user.id)
                else:
                    await manager.broadcast_to_channel(channel_id, {
                        "type":      "call_terminated",
                        "ended_by":  user.full_name,
                        "call_uuid": call_uuid,
                    })   
 
            elif msg_type == "call_reject":
                target_user_id = data.get("target_user_id")
                call_uuid      = data.get("call_uuid", "")
                if target_user_id:
                    await manager.send_to_user(int(target_user_id), {
                        "type":           "call_rejected",
                        "rejected_by":    user.full_name,
                        "rejected_by_id": user.id,
                        "call_uuid":      call_uuid,
                    })
 
            elif msg_type == "call_missed":
                call_uuid = data.get("call_uuid", "")
                await manager.broadcast_to_channel(channel_id, {
                    "type":      "call_missed",
                    "call_uuid": call_uuid,
                    "caller_id": user.id,
                })
                    
                    
    except WebSocketDisconnect:
        manager.disconnect_from_channel(websocket, channel_id, user.id)
        await manager.broadcast_to_channel(channel_id, {
            "type": "user_left",
            "user_id": user.id,
            "user_name": user.full_name,
        })
    except Exception as e:
        logger.error(f"WS error for user {user.id}: {e}")
        manager.disconnect_from_channel(websocket, channel_id, user.id)


@router.post("/schedule")
async def schedule_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.models import ScheduledMessage
 
    body = await request.json()
    channel_id   = body.get("channel_id")
    content      = (body.get("content") or "").strip()
    scheduled_at = body.get("scheduled_at", "")
 
    if not channel_id or not content or not scheduled_at:
        return JSONResponse(
            {"error": "channel_id, content and scheduled_at required"},
            status_code=400
        )
 
    try:
        clean = scheduled_at.replace("Z", "+00:00")
        sched_dt = datetime.fromisoformat(clean)
        if sched_dt.tzinfo is not None:
            sched_dt = sched_dt.replace(tzinfo=None)
    except (ValueError, AttributeError):
        try:
            sched_dt = datetime.strptime(scheduled_at[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            return JSONResponse({"error": "Invalid date format"}, status_code=400)
 
    if sched_dt <= datetime.utcnow():
        return JSONResponse({"error": "Scheduled time must be in the future"}, status_code=400)
 
    sm = ScheduledMessage(
        channel_id=channel_id,
        sender_id=current_user.id,
        content=content,
        scheduled_at=sched_dt,
    )
    db.add(sm)
    await db.commit()
    await db.refresh(sm)
 
    return JSONResponse({
        "id": sm.id,
        "scheduled_at": sm.scheduled_at.isoformat(),
        "content": sm.content,
    })
    

 
@router.get("/scheduled")
async def list_scheduled(
    channel_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.models import ScheduledMessage
    rows = (await db.execute(
        select(ScheduledMessage)
        .where(
            ScheduledMessage.channel_id == channel_id,
            ScheduledMessage.sender_id == current_user.id,
            ScheduledMessage.sent == False,
            ScheduledMessage.cancelled == False,
        )
        .order_by(ScheduledMessage.scheduled_at.asc())
    )).scalars().all()
    return JSONResponse([{
        "id": s.id, "content": s.content,
        "scheduled_at": s.scheduled_at.isoformat(),
    } for s in rows])
 
 
@router.delete("/scheduled/{sm_id}")
async def cancel_scheduled(
    sm_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.models import ScheduledMessage
    sm = (await db.execute(
        select(ScheduledMessage).where(
            ScheduledMessage.id == sm_id,
            ScheduledMessage.sender_id == current_user.id,
        )
    )).scalar_one_or_none()
    if not sm: raise HTTPException(404)
    sm.cancelled = True
    await db.commit()
    return JSONResponse({"status": "cancelled"})
 
@router.post("/{message_id}/pin")
async def pin_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.models import PinnedMessage
    msg = (await db.execute(select(Message).where(Message.id == message_id))).scalar_one_or_none()
    if not msg: raise HTTPException(404)
 
    existing = (await db.execute(
        select(PinnedMessage).where(
            PinnedMessage.message_id == message_id,
            PinnedMessage.channel_id == msg.channel_id,
        )
    )).scalar_one_or_none()
 
    if existing:
        await db.delete(existing)
        await db.commit()
        action = "unpinned"
    else:
        db.add(PinnedMessage(
            channel_id=msg.channel_id,
            message_id=message_id,
            pinned_by=current_user.id,
        ))
        await db.commit()
        action = "pinned"
 
    await manager.broadcast_to_channel(msg.channel_id, {
        "type": "pin_update",
        "message_id": message_id,
        "action": action,
        "pinned_by": current_user.full_name,
    })
    return JSONResponse({"status": action})
 
 
@router.get("/channel/{channel_id}/pinned")
async def get_pinned(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.models import PinnedMessage
    rows = (await db.execute(
        select(PinnedMessage, Message, User.full_name.label("sender_name"), User.avatar_color)
        .join(Message, PinnedMessage.message_id == Message.id)
        .join(User, Message.sender_id == User.id)
        .where(PinnedMessage.channel_id == channel_id)
        .order_by(PinnedMessage.pinned_at.desc())
        .limit(20)
    )).all()
    return JSONResponse([{
        "id": pin.id,
        "message_id": msg.id,
        "content": msg.content,
        "sender_name": name,
        "avatar_color": color,
        "pinned_at": pin.pinned_at.isoformat() if pin.pinned_at else "",
    } for pin, msg, name, color in rows])
 

@router.post("/{message_id}/edit")
async def edit_message(
    message_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.models import MessageEdit
    body = await request.json()
    new_content = (body.get("content") or "").strip()
    if not new_content:
        return JSONResponse({"error": "Content cannot be empty"}, status_code=400)
 
    msg = (await db.execute(select(Message).where(Message.id == message_id))).scalar_one_or_none()
    if not msg: raise HTTPException(404)
    if msg.sender_id != current_user.id:
        return JSONResponse({"error": "You can only edit your own messages"}, status_code=403)
    if msg.is_deleted:
        return JSONResponse({"error": "Cannot edit a deleted message"}, status_code=400)

    db.add(MessageEdit(
        message_id=message_id,
        old_content=msg.content or "",
        new_content=new_content,
        edited_by=current_user.id,
    ))
 
    old_content = msg.content
    msg.content = new_content
    msg.edited_at = datetime.utcnow()
    await db.commit()
 
    await manager.broadcast_to_channel(msg.channel_id, {
        "type": "message_edited",
        "message_id": message_id,
        "new_content": new_content,
        "edited_by": current_user.full_name,
        "edited_at": msg.edited_at.isoformat(),
    })
    return JSONResponse({"status": "edited", "new_content": new_content})
 
 
@router.get("/{message_id}/edit-history")
async def edit_history(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.models import MessageEdit
    rows = (await db.execute(
        select(MessageEdit)
        .where(MessageEdit.message_id == message_id)
        .order_by(MessageEdit.edited_at.desc())
    )).scalars().all()
    return JSONResponse([{
        "old_content": r.old_content,
        "new_content": r.new_content,
        "edited_at": r.edited_at.isoformat() if r.edited_at else "",
    } for r in rows])