from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import AIConversation, AIMessage, User
from app.auth import require_user
from app.services.ai_service import ai_service
import uuid
import json

router = APIRouter(prefix="/ask-boss", tags=["ask_boss"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def ask_boss_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    sessions = (await db.execute(
        select(AIConversation)
        .where(AIConversation.user_id == current_user.id)
        .order_by(AIConversation.created_at.desc())
        .limit(10)
    )).scalars().all()

    ai_online = await ai_service.check_ollama_health()

    return templates.TemplateResponse(
        request=request,
        name="ask_boss/index.html",
        context={
            "user": current_user,
            "sessions": sessions,
            "ai_online": ai_online,
            "page": "ask_boss",
        }
    )


@router.post("/session/new")
async def new_session(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    session_id = str(uuid.uuid4())
    convo = AIConversation(user_id=current_user.id, session_id=session_id)
    db.add(convo)
    await db.commit()
    await db.refresh(convo)
    return JSONResponse({"session_id": session_id, "id": convo.id})


@router.get("/session/{session_id}/history")
async def get_session_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    convo = (await db.execute(
        select(AIConversation)
        .where(AIConversation.session_id == session_id, AIConversation.user_id == current_user.id)
    )).scalar_one_or_none()

    if not convo:
        return JSONResponse([])

    msgs = (await db.execute(
        select(AIMessage)
        .where(AIMessage.conversation_id == convo.id)
        .order_by(AIMessage.created_at.asc())
    )).scalars().all()

    return JSONResponse([
        {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in msgs
    ])


@router.post("/chat")
async def chat(
    request: Request,
    db: AsyncSession = Depends(get_db),
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
        select(AIMessage)
        .where(AIMessage.conversation_id == convo.id)
        .order_by(AIMessage.created_at.asc())
        .limit(20)
    )).scalars().all()

    history = [{"role": m.role, "content": m.content} for m in history_msgs]
    context_chunks = await ai_service.retrieve_context(
        user_message, db, user_role=current_user.role, department=current_user.department
    )
    messages = await ai_service.build_prompt(user_message, history, context_chunks)

    user_msg = AIMessage(conversation_id=convo.id, role="user", content=user_message)
    db.add(user_msg)
    await db.commit()

    session_id_final = convo.session_id

    async def stream_response():
        full_response = ""
        async for chunk in ai_service.chat_stream(messages):
            full_response += chunk
            yield f"data: {json.dumps({'content': chunk, 'session_id': session_id_final})}\n\n"

        async with db.begin():
            db.add(AIMessage(
                conversation_id=convo.id,
                role="assistant",
                content=full_response,
                sources=[c["source"] for c in context_chunks],
            ))

        yield f"data: {json.dumps({'done': True, 'session_id': session_id_final})}\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")