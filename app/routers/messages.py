# src/app/routers/messages.py
import os
import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.database import get_db, AsyncSessionLocal
from app.models import Channel, ChannelMember, Message, User, KnowledgeChunk
from app.auth import require_user
from app.services.websocket_manager import manager
from app.services.ai_service import ai_service
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["messages"])
templates = Jinja2Templates(directory="app/templates")

DEPARTMENTS = ["HR", "Sales", "Technology", "Finance", "Operations", "Legal", "Marketing", "Management", "General"]

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv",
    "py", "js", "ts", "html", "json", "md",
    "zip", "rar", "7z",
    "mp3", "wav", "mp4", "mov", "avi",
}

STATIC_UPLOAD_DIR = os.path.join("app", "static", "uploads", "messages")


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

    return templates.TemplateResponse(
        request=request,
        name="messages/index.html",
        context={
            "user": current_user,
            "channels": channels,
            "all_users": all_users,
            "all_channels": all_channels,
            "member_channel_ids": member_channel_ids,
            "departments": DEPARTMENTS,
            "page": "messages",
        }
    )


# ── HISTORY ────────────────────────────────────────────────────────────────────

@router.get("/channel/{channel_id}/history")
async def get_channel_history(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    stmt = (
        select(Message, User.full_name, User.avatar_color)
        .join(User, Message.sender_id == User.id)
        .where(Message.channel_id == channel_id)
        .order_by(Message.created_at.asc())
        .limit(100)
    )
    result = await db.execute(stmt)
    messages = []
    for msg, name, color in result.all():
        messages.append(_serialize_message(msg, name, color))
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
        .where(Message.channel_id == channel.id)
        .order_by(Message.created_at.asc())
        .limit(100)
    )
    result = await db.execute(stmt)
    messages = []
    for msg, name, color in result.all():
        messages.append(_serialize_message(msg, name, color))

    return JSONResponse({"channel_id": channel.id, "messages": messages})


def _serialize_message(msg: Message, sender_name: str, avatar_color: str) -> dict:
    """Serialize a Message row to a dict. All fields match models.py Message columns."""
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
        # Reply fields
        "reply_to_id": msg.reply_to_id,
        "reply_to_sender": msg.reply_to_sender,
        "reply_to_content": msg.reply_to_content,
        # File fields
        "file_url": msg.file_url,
        "file_name": msg.file_name,
        "file_size": msg.file_size,
    }


# ── DM HELPER ──────────────────────────────────────────────────────────────────

async def _get_or_create_dm(db: AsyncSession, user_a: int, user_b: int) -> Channel:
    dm_name = f"dm_{min(user_a, user_b)}_{max(user_a, user_b)}"
    existing = (await db.execute(
        select(Channel).where(
            Channel.name == dm_name,
            Channel.channel_type == "direct"
        )
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
        name=name,
        description=description,
        department=",".join(dept_list),
        channel_type="department",
        created_by=current_user.id,
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
            and_(ChannelMember.channel_id == channel_id,
                 ChannelMember.user_id == current_user.id)
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
    channel = (await db.execute(
        select(Channel).where(Channel.id == channel_id)
    )).scalar_one_or_none()
    if not channel:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if channel.created_by != current_user.id and current_user.role not in ("super_admin", "admin"):
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    dept_list = [d.strip() for d in departments.split(",") if d.strip()]
    channel.name = name
    channel.description = description
    channel.department = ",".join(dept_list)

    await db.execute(
        ChannelMember.__table__.delete().where(
            and_(ChannelMember.channel_id == channel_id,
                 ChannelMember.user_id != current_user.id)
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    # Validate extension
    ext = Path(file.filename or "").suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse({"error": f"File type '.{ext}' not allowed"}, status_code=400)

    # Read & size-check
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
            content=None,                       # nullable=True for file messages
            message_type="file",
            file_url=file_url,
            file_name=file.filename,            # models.py: file_name VARCHAR(255)
            file_size=len(data),                # models.py: file_size INTEGER
            reply_to_id=reply_to_id,
            reply_to_sender=reply_to_sender,
            reply_to_content=reply_to_content,
            is_deleted=False,
            is_ai_extracted=False,
        )
        sess.add(msg)
        await sess.commit()
        await sess.refresh(msg)

        payload = {
            "type": "message",
            **_serialize_message(msg, current_user.full_name, current_user.avatar_color),
        }
        await manager.broadcast_to_channel(channel_id, payload)

    return JSONResponse({"status": "ok", "file_url": file_url})


# ── DELETE MESSAGE ─────────────────────────────────────────────────────────────

@router.post("/{message_id}/delete")
async def delete_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    msg = (await db.execute(
        select(Message).where(Message.id == message_id)
    )).scalar_one_or_none()

    if not msg:
        return JSONResponse({"error": "Not found"}, status_code=404)

    is_admin = current_user.role in ("super_admin", "admin")
    if msg.sender_id != current_user.id and not is_admin:
        return JSONResponse({"error": "Not authorized"}, status_code=403)

    msg.is_deleted = True
    msg.content = None                          # nullable=True, clear content on delete
    await db.commit()

    await manager.broadcast_to_channel(msg.channel_id, {
        "type": "message_deleted",
        "message_id": message_id,
    })

    return JSONResponse({"status": "deleted"})


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

                async with AsyncSessionLocal() as sess:
                    msg = Message(
                        channel_id=channel_id,
                        sender_id=user.id,
                        content=content,
                        message_type="text",
                        reply_to_id=data.get("reply_to_id"),
                        reply_to_sender=data.get("reply_to_sender"),
                        reply_to_content=data.get("reply_to_content"),
                        is_deleted=False,
                        is_ai_extracted=False,
                        # file fields are NULL for text messages
                        file_url=None,
                        file_name=None,
                        file_size=None,
                    )
                    sess.add(msg)
                    await sess.commit()
                    await sess.refresh(msg)

                    payload_out = {
                        "type": "message",
                        **_serialize_message(msg, user.full_name, user.avatar_color),
                    }
                    await manager.broadcast_to_channel(channel_id, payload_out)

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

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect_from_channel(websocket, channel_id, user.id)
        await manager.broadcast_to_channel(channel_id, {
            "type": "user_left",
            "user_id": user.id,
            "user_name": user.full_name,
        })
    except Exception as e:
        logger.error(f"WS error: {e}")
        manager.disconnect_from_channel(websocket, channel_id, user.id)