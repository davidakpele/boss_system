# app/routers/ask_boss.py
from http.client import HTTPException

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db, AsyncSessionLocal
from app.models import AIConversation, AIMessage, User, Document, OnboardingConversation
from app.auth import require_user
from app.services.ai_service import ai_service
from app.services.websocket_manager import manager
import uuid, json, asyncio, logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask-boss", tags=["ask_boss"])
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
async def ask_boss_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    sessions = (await db.execute(
        select(AIConversation)
        .where(AIConversation.user_id == current_user.id)
        .order_by(AIConversation.created_at.desc()).limit(10)
    )).scalars().all()
    ai_online = await ai_service.check_ollama_health()
    return templates.TemplateResponse(request=request, name="ask_boss/index.html", context={
        "user": current_user, "sessions": sessions, "ai_online": ai_online, "page": "ask_boss",
    })


@router.post("/session/new")
async def new_session(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user)):
    session_id = str(uuid.uuid4())
    convo = AIConversation(user_id=current_user.id, session_id=session_id)
    db.add(convo)
    await db.commit()
    await db.refresh(convo)
    return JSONResponse({"session_id": session_id, "id": convo.id})


@router.get("/session/{session_id}/history")
async def get_session_history(
    session_id: str, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    convo = (await db.execute(
        select(AIConversation)
        .where(AIConversation.session_id == session_id, AIConversation.user_id == current_user.id)
    )).scalar_one_or_none()
    if not convo:
        return JSONResponse([])
    msgs = (await db.execute(
        select(AIMessage).where(AIMessage.conversation_id == convo.id)
        .order_by(AIMessage.created_at.asc())
    )).scalars().all()
    return JSONResponse([
        {
            "role": m.role, "content": m.content,
            "created_at": m.created_at.isoformat(),
            "source_chunks": m.source_chunks or [],
        }
        for m in msgs
    ])


@router.post("/chat")
async def chat(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    body = await request.json()
    session_id = body.get("session_id")
    user_message = body.get("message", "").strip()
    if not user_message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    convo = None
    if session_id:
        convo = (await db.execute(
            select(AIConversation)
            .where(AIConversation.session_id == session_id, AIConversation.user_id == current_user.id)
        )).scalar_one_or_none()
    if not convo:
        convo = AIConversation(user_id=current_user.id, session_id=str(uuid.uuid4()))
        db.add(convo)
        await db.flush()

    history_msgs = (await db.execute(
        select(AIMessage).where(AIMessage.conversation_id == convo.id)
        .order_by(AIMessage.created_at.asc()).limit(20)
    )).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in history_msgs]

    context_chunks = await ai_service.retrieve_context(
        user_message, db, user_role=current_user.role, department=current_user.department
    )
    for chunk in context_chunks:
        if chunk.get("document_id"):
            doc = (await db.execute(
                select(Document).where(Document.id == chunk["document_id"])
            )).scalar_one_or_none()
            if doc:
                chunk["document_title"] = doc.title
                chunk["document_dept"] = doc.department or ""

    messages = await ai_service.build_prompt(user_message, history, context_chunks)
    db.add(AIMessage(conversation_id=convo.id, role="user", content=user_message))
    await db.commit()

    session_id_final = convo.session_id
    convo_id = convo.id

    async def stream_response():
        full_response = ""
        async for chunk in ai_service.chat_stream(messages):
            full_response += chunk
            yield f"data: {json.dumps({'content': chunk, 'session_id': session_id_final})}\n\n"
        async with AsyncSessionLocal() as save_db:
            save_db.add(AIMessage(
                conversation_id=convo_id,
                role="assistant",
                content=full_response,
                sources=[c.get("chunk_id") for c in context_chunks],
                source_chunks=context_chunks,
            ))
            await save_db.commit()
        yield f"data: {json.dumps({'done': True, 'session_id': session_id_final, 'sources': context_chunks})}\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")

#  ONBOARDING WEBSOCKET
#  Single socket handles: status, chat, AI token streaming
#
#  Client → Server:
#    { "type": "ping" }
#    { "type": "chat", "message": "..." }
#
#  Server → Client:
#    { "type": "pong" }
#    { "type": "status", "ai_online": bool, "user_online": true }
#    { "type": "token", "content": "..." }
#    { "type": "done" }
#    { "type": "error", "message": "..." }

@router.websocket("/onboarding-assistant/ws/{user_id}")
async def onboarding_ws(websocket: WebSocket, user_id: int, token: str = None):
    from jose import jwt
    from app.config import settings as cfg
    authed_user = None
    try:
        if token:
            payload = jwt.decode(token, cfg.SECRET_KEY, algorithms=[cfg.ALGORITHM])
            uid = int(payload.get("sub"))
            async with AsyncSessionLocal() as sess:
                res = await sess.execute(select(User).where(User.id == uid))
                authed_user = res.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Onboarding WS auth error: {e}")
    if not authed_user:
        await websocket.accept()
        await websocket.close(code=4001)
        return
    await websocket.accept()
    manager.user_connections[authed_user.id] = websocket
    logger.info(f"Onboarding WS connected: user {authed_user.id}")
    ai_online = await ai_service.check_ollama_health()
    await websocket.send_json({"type": "status", "ai_online": ai_online, "user_online": True})
    async def status_loop():
        while True:
            await asyncio.sleep(30)
            try:
                online = await ai_service.check_ollama_health()
                await websocket.send_json({"type": "status", "ai_online": online, "user_online": True})
            except Exception:
                break

    status_task = asyncio.create_task(status_loop())

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "chat":
                user_message = (data.get("message") or "").strip()
                if not user_message:
                    continue
                async with AsyncSessionLocal() as db:
                    history_rows = (await db.execute(
                        select(OnboardingConversation)
                        .where(OnboardingConversation.user_id == authed_user.id)
                        .order_by(OnboardingConversation.created_at.asc())
                        .limit(20)
                    )).scalars().all()
                    history = [{"role": r.role, "content": r.content} for r in history_rows]
                    db.add(OnboardingConversation(
                        user_id=authed_user.id, role="user", content=user_message
                    ))
                    await db.commit()

                full_response = ""
                try:
                    async with AsyncSessionLocal() as db:
                        async for token_chunk in ai_service.onboarding_chat(
                            user_message,
                            history,
                            authed_user.full_name,
                            authed_user.department or "General",
                            db,
                        ):
                            full_response += token_chunk
                            await websocket.send_json({"type": "token", "content": token_chunk})
                except Exception as e:
                    logger.error(f"AI stream error: {e}")
                    await websocket.send_json({"type": "error", "message": "AI service error. Please try again."})
                    continue
                async with AsyncSessionLocal() as db:
                    db.add(OnboardingConversation(
                        user_id=authed_user.id, role="assistant", content=full_response
                    ))
                    await db.commit()

                await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        logger.info(f"Onboarding WS disconnected: user {authed_user.id}")
    except Exception as e:
        logger.error(f"Onboarding WS error: {e}")
    finally:
        status_task.cancel()
        if manager.user_connections.get(authed_user.id) is websocket:
            del manager.user_connections[authed_user.id]


@router.post("/meeting-summary/{channel_id}")
async def generate_channel_summary(
    channel_id: int, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.models import Message, Channel, MeetingSummary
    from datetime import date

    channel = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not channel:
        return JSONResponse({"error": "Channel not found"}, status_code=404)

    msgs = (await db.execute(
        select(Message, User.full_name)
        .join(User, Message.sender_id == User.id)
        .where(Message.channel_id == channel_id, Message.message_type == "text")
        .order_by(Message.created_at.desc()).limit(60)
    )).all()

    if not msgs:
        return JSONResponse({"error": "No messages to summarize"}, status_code=400)

    msg_list = [{"sender_name": name, "content": m.content} for m, name in reversed(msgs)]
    summary_text = await ai_service.generate_meeting_summary(msg_list, channel.name)
    if not summary_text:
        return JSONResponse({"error": "Could not generate summary"}, status_code=422)

    ms = MeetingSummary(
        channel_id=channel_id, summary=summary_text,
        message_count=len(msg_list), generated_for_date=str(date.today()),
    )
    db.add(ms)
    await db.commit()
    await db.refresh(ms)
    return JSONResponse({"id": ms.id, "summary": summary_text,
                         "message_count": len(msg_list), "channel_name": channel.name})

@router.get("/meeting-summaries/{channel_id}")
async def get_channel_summaries(
    channel_id: int, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.models import MeetingSummary
    summaries = (await db.execute(
        select(MeetingSummary).where(MeetingSummary.channel_id == channel_id)
        .order_by(MeetingSummary.generated_at.desc()).limit(10)
    )).scalars().all()
    return JSONResponse([
        {"id": s.id, "summary": s.summary, "message_count": s.message_count,
         "generated_at": s.generated_at.isoformat(), "date": s.generated_for_date}
        for s in summaries
    ])
    
@router.patch("/session/{session_id}/rename")
async def rename_session(
    session_id: str, request: Request,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        return JSONResponse({"error": "Title required"}, status_code=400)
    convo = (await db.execute(
        select(AIConversation)
        .where(AIConversation.session_id == session_id, AIConversation.user_id == current_user.id)
    )).scalar_one_or_none()
    if not convo:
        raise HTTPException(404)
    convo.title = title
    await db.commit()
    return JSONResponse({"status": "renamed", "title": title})


@router.delete("/session/{session_id}")
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(require_user),
):
    convo = (await db.execute(
        select(AIConversation)
        .where(AIConversation.session_id == session_id, AIConversation.user_id == current_user.id)
    )).scalar_one_or_none()
    if not convo:
        raise HTTPException(404)
    msgs = (await db.execute(
        select(AIMessage).where(AIMessage.conversation_id == convo.id)
    )).scalars().all()
    for m in msgs:
        await db.delete(m)
    await db.delete(convo)
    await db.commit()
    return JSONResponse({"status": "deleted"})