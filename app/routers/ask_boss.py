# app/routers/ask_boss.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import AIConversation, AIMessage, User, Document, OnboardingConversation
from app.auth import require_user
from app.services.ai_service import ai_service
import uuid, json

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

    # ── Vector / keyword RAG ──
    context_chunks = await ai_service.retrieve_context(
        user_message, db, user_role=current_user.role, department=current_user.department
    )

    # ── Enrich chunks with document titles for citation ──
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

        # Save assistant reply with citation metadata
        from app.database import AsyncSessionLocal
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


# ─────────────────────────────────────────────────────────────────
#  ONBOARDING ASSISTANT  (separate endpoint for new employees)
# ─────────────────────────────────────────────────────────────────
@router.get("/onboarding-assistant", response_class=HTMLResponse)
async def onboarding_assistant_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    # Load chat history for this user
    history = (await db.execute(
        select(OnboardingConversation)
        .where(OnboardingConversation.user_id == current_user.id)
        .order_by(OnboardingConversation.created_at.asc())
        .limit(40)
    )).scalars().all()
    ai_online = await ai_service.check_ollama_health()
    return templates.TemplateResponse(request=request, name="ask_boss/onboarding_assistant.html", context={
        "user": current_user, "history": history, "ai_online": ai_online, "page": "ask_boss",
    })


@router.post("/onboarding-assistant/chat")
async def onboarding_chat(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    body = await request.json()
    user_message = body.get("message", "").strip()
    if not user_message:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    # Load recent history
    history_rows = (await db.execute(
        select(OnboardingConversation)
        .where(OnboardingConversation.user_id == current_user.id)
        .order_by(OnboardingConversation.created_at.asc()).limit(20)
    )).scalars().all()
    history = [{"role": r.role, "content": r.content} for r in history_rows]

    # Save user message
    db.add(OnboardingConversation(user_id=current_user.id, role="user", content=user_message))
    await db.commit()
    user_id = current_user.id
    user_name = current_user.full_name
    dept = current_user.department or "General"

    async def stream():
        full = ""
        async for chunk in ai_service.onboarding_chat(user_message, history, user_name, dept, db):
            full += chunk
            yield f"data: {json.dumps({'content': chunk})}\n\n"
        # Save assistant reply
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as save_db:
            save_db.add(OnboardingConversation(user_id=user_id, role="assistant", content=full))
            await save_db.commit()
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ─────────────────────────────────────────────────────────────────
#  MEETING SUMMARY  (manual trigger + auto via messages router)
# ─────────────────────────────────────────────────────────────────
@router.post("/meeting-summary/{channel_id}")
async def generate_channel_summary(
    channel_id: int, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    from app.models import Message, Channel, MeetingSummary
    from datetime import date

    channel = (await db.execute(
        select(Channel).where(Channel.id == channel_id)
    )).scalar_one_or_none()
    if not channel:
        return JSONResponse({"error": "Channel not found"}, status_code=404)

    # Get last 60 messages
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

    # Store
    ms = MeetingSummary(
        channel_id=channel_id,
        summary=summary_text,
        message_count=len(msg_list),
        generated_for_date=str(date.today()),
    )
    db.add(ms)
    await db.commit()
    await db.refresh(ms)

    return JSONResponse({
        "id": ms.id,
        "summary": summary_text,
        "message_count": len(msg_list),
        "channel_name": channel.name,
    })


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