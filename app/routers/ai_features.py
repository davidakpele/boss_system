# app/routers/ai_features.py
"""
AI-Powered Features Router
  POST /ai/writing/assist          — writing assistant (improve/expand/shorten/translate)
  POST /ai/documents/{id}/qa       — document Q&A with citations
  POST /ai/documents/{id}/auto-tag — auto-tag a document
  POST /ai/knowledge/auto-tag      — auto-tag all untagged knowledge chunks
  GET  /ai/sentiment               — sentiment dashboard page
  POST /ai/sentiment/analyse       — run sentiment analysis on a channel
  GET  /ai/sentiment/data          — JSON: sentiment history
  GET  /ai/meeting                 — meeting intelligence page
  POST /ai/meeting/analyse         — analyse a transcript
  GET  /ai/meeting/{id}            — view a saved transcript analysis
  GET  /ai/meeting/list            — list all transcripts
"""
import json
import logging
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models import (
    User, Document, KnowledgeChunk, Channel, Message,
    DocumentTag, SentimentLog, MeetingTranscript, UserRole
)
from app.auth import require_user
from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai-features"])
templates = Jinja2Templates(directory="app/templates")


# ══════════════════════════════════════════════════════════════════════════════
#  1. WRITING ASSISTANT
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/writing/assist")
async def writing_assist(
    request: Request,
    current_user: User = Depends(require_user),
):
    body = await request.json()
    text   = (body.get("text") or "").strip()
    action = (body.get("action") or "improve").strip()
    lang   = (body.get("language") or "").strip() or None

    if not text:
        return JSONResponse({"error": "No text provided"}, status_code=400)
    if len(text) > 5000:
        return JSONResponse({"error": "Text too long (max 5000 chars)"}, status_code=400)

    result = await ai_service.improve_text(text, action, lang)
    return JSONResponse({"result": result, "action": action})


# ══════════════════════════════════════════════════════════════════════════════
#  2. DOCUMENT Q&A WITH CITATIONS
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/documents/{doc_id}/qa")
async def document_qa(
    doc_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    body = await request.json()
    question = (body.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "No question"}, status_code=400)

    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404)

    result = await ai_service.answer_with_citations(question, db, document_id=doc_id)
    return JSONResponse(result)


@router.post("/knowledge/qa")
async def knowledge_qa(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Q&A across the full knowledge base (no document restriction)."""
    body = await request.json()
    question = (body.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "No question"}, status_code=400)
    result = await ai_service.answer_with_citations(question, db)
    return JSONResponse(result)


# ══════════════════════════════════════════════════════════════════════════════
#  3. AUTO-TAGGING
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/documents/{doc_id}/auto-tag")
async def auto_tag_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404)

    text = f"{doc.title}\n{doc.description or ''}\n{doc.content or ''}"
    existing = (await db.execute(
        select(DocumentTag.tag).where(DocumentTag.document_id == doc_id)
    )).scalars().all()

    tag_data = await ai_service.generate_tags(text, list(existing))

    # Delete old AI tags, preserve manual
    await db.execute(
        DocumentTag.__table__.delete().where(
            DocumentTag.document_id == doc_id,
            DocumentTag.source == "ai"
        )
    )

    # Save new tags
    for topic in tag_data["topics"]:
        db.add(DocumentTag(document_id=doc_id, tag=topic, tag_type="topic", source="ai"))
    for kw in tag_data["keywords"]:
        db.add(DocumentTag(document_id=doc_id, tag=kw, tag_type="keyword", source="ai"))
    db.add(DocumentTag(document_id=doc_id, tag=tag_data["category"], tag_type="category", source="ai"))
    db.add(DocumentTag(document_id=doc_id, tag=tag_data["sentiment"], tag_type="sentiment", source="ai",
                       confidence=0.8))

    # Update doc tags JSON field if it exists
    if hasattr(doc, "tags"):
        all_tags = tag_data["topics"] + tag_data["keywords"] + [tag_data["category"]]
        doc.tags = all_tags

    await db.commit()
    return JSONResponse({"status": "tagged", "tags": tag_data})


@router.post("/knowledge/bulk-tag")
async def bulk_tag_knowledge(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Auto-tag up to 50 untagged knowledge chunks."""
    if current_user.role not in (UserRole.super_admin, UserRole.admin):
        raise HTTPException(status_code=403)

    # Find chunks with no tags yet
    tagged_chunk_ids = (await db.execute(
        select(DocumentTag.chunk_id).where(DocumentTag.chunk_id != None)
    )).scalars().all()

    chunks = (await db.execute(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.id.notin_(tagged_chunk_ids))
        .limit(50)
    )).scalars().all()

    tagged_count = 0
    for ch in chunks:
        try:
            tag_data = await ai_service.generate_tags(ch.content or ch.summary or "")
            for topic in tag_data["topics"]:
                db.add(DocumentTag(chunk_id=ch.id, tag=topic, tag_type="topic", source="ai"))
            for kw in tag_data["keywords"]:
                db.add(DocumentTag(chunk_id=ch.id, tag=kw, tag_type="keyword", source="ai"))
            tagged_count += 1
        except Exception as e:
            logger.warning(f"Tagging chunk {ch.id} failed: {e}")

    await db.commit()
    return JSONResponse({"tagged": tagged_count, "total": len(chunks)})


@router.get("/documents/{doc_id}/tags")
async def get_document_tags(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    tags = (await db.execute(
        select(DocumentTag).where(DocumentTag.document_id == doc_id)
        .order_by(DocumentTag.tag_type, DocumentTag.tag)
    )).scalars().all()
    return JSONResponse([{"id":t.id,"tag":t.tag,"type":t.tag_type,"source":t.source} for t in tags])


@router.post("/documents/{doc_id}/tags/add")
async def add_manual_tag(
    doc_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    body = await request.json()
    tag = (body.get("tag") or "").strip()
    if not tag:
        return JSONResponse({"error": "No tag"}, status_code=400)
    db.add(DocumentTag(document_id=doc_id, tag=tag, tag_type="keyword", source="manual"))
    await db.commit()
    return JSONResponse({"status": "added"})


@router.delete("/documents/tags/{tag_id}")
async def delete_tag(
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    tag = (await db.execute(select(DocumentTag).where(DocumentTag.id == tag_id))).scalar_one_or_none()
    if tag:
        await db.delete(tag)
        await db.commit()
    return JSONResponse({"status": "deleted"})


# ══════════════════════════════════════════════════════════════════════════════
#  4. SENTIMENT ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/sentiment", response_class=HTMLResponse)
async def sentiment_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in (UserRole.super_admin, UserRole.admin, UserRole.manager):
        raise HTTPException(status_code=403)

    channels = (await db.execute(
        select(Channel).where(Channel.channel_type == "department").order_by(Channel.name)
    )).scalars().all()

    # Latest snapshot per channel
    recent_logs = (await db.execute(
        select(SentimentLog).order_by(SentimentLog.created_at.desc()).limit(30)
    )).scalars().all()

    return templates.TemplateResponse(request=request, name="ai/sentiment.html", context={
        "user": current_user, "page": "ai",
        "channels": channels, "recent_logs": recent_logs,
    })


@router.post("/sentiment/analyse")
async def analyse_sentiment(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    if current_user.role not in (UserRole.super_admin, UserRole.admin, UserRole.manager):
        raise HTTPException(status_code=403)

    body = await request.json()
    channel_id = body.get("channel_id")
    days = int(body.get("days", 7))

    since = datetime.utcnow() - timedelta(days=days)

    if channel_id:
        channel = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
        ch_name = channel.name if channel else ""
        msgs = (await db.execute(
            select(Message.content)
            .where(Message.channel_id == channel_id,
                   Message.created_at >= since,
                   Message.is_deleted == False,
                   Message.content != None,
                   Message.message_type == "text")
            .order_by(Message.created_at.desc()).limit(100)
        )).scalars().all()
    else:
        ch_name = "All Channels"
        msgs = (await db.execute(
            select(Message.content)
            .where(Message.created_at >= since,
                   Message.is_deleted == False,
                   Message.content != None,
                   Message.message_type == "text")
            .order_by(Message.created_at.desc()).limit(150)
        )).scalars().all()

    if not msgs:
        return JSONResponse({"error": "Not enough messages to analyse"}, status_code=422)

    result = await ai_service.analyse_channel_sentiment([m for m in msgs if m], ch_name)

    # Save snapshot
    log = SentimentLog(
        channel_id=channel_id,
        period_date=date.today(),
        score=result["score"],
        label=result["label"],
        themes=result["themes"],
        summary=result["summary"],
        sample_size=len(msgs),
    )
    if channel_id:
        channel = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
        log.department = channel.department if channel else None
    db.add(log)
    await db.commit()

    return JSONResponse({**result, "sample_size": len(msgs), "channel": ch_name, "days": days})


@router.get("/sentiment/data")
async def sentiment_data(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    days: int = 30,
):
    since = date.today() - timedelta(days=days)
    logs = (await db.execute(
        select(SentimentLog)
        .where(SentimentLog.period_date >= since)
        .order_by(SentimentLog.period_date.asc())
    )).scalars().all()
    return JSONResponse([{
        "date":     str(l.period_date),
        "score":    l.score,
        "label":    l.label,
        "themes":   l.themes,
        "summary":  l.summary,
        "channel_id": l.channel_id,
        "sample_size": l.sample_size,
    } for l in logs])


# ══════════════════════════════════════════════════════════════════════════════
#  5. MEETING INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/meeting", response_class=HTMLResponse)
async def meeting_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    transcripts = (await db.execute(
        select(MeetingTranscript)
        .order_by(MeetingTranscript.created_at.desc()).limit(30)
    )).scalars().all()
    return templates.TemplateResponse(request=request, name="ai/meeting.html", context={
        "user": current_user, "page": "ai",
        "transcripts": transcripts,
    })


@router.post("/meeting/analyse")
async def analyse_meeting(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    body = await request.json()
    transcript = (body.get("transcript") or "").strip()
    title      = (body.get("title") or "Untitled Meeting").strip()
    meeting_date = body.get("date")

    if len(transcript) < 100:
        return JSONResponse({"error": "Transcript too short (min 100 characters)"}, status_code=400)

    result = await ai_service.analyse_meeting_transcript(transcript, title)

    # Save to DB
    mt = MeetingTranscript(
        title=title,
        raw_transcript=transcript,
        meeting_date=datetime.fromisoformat(meeting_date) if meeting_date else None,
        duration_mins=result.get("duration_estimate"),
        participants=result.get("participants", []),
        action_items=result.get("action_items", []),
        decisions=result.get("decisions", []),
        key_topics=result.get("key_topics", []),
        summary=result.get("summary", ""),
        sentiment_score=result.get("sentiment_score"),
        created_by=current_user.id,
    )
    db.add(mt)
    await db.commit()
    await db.refresh(mt)

    return JSONResponse({**result, "id": mt.id, "title": title})


@router.get("/meeting/{transcript_id}")
async def get_transcript(
    transcript_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    mt = (await db.execute(
        select(MeetingTranscript).where(MeetingTranscript.id == transcript_id)
    )).scalar_one_or_none()
    if not mt:
        raise HTTPException(status_code=404)
    return JSONResponse({
        "id": mt.id, "title": mt.title,
        "summary": mt.summary, "action_items": mt.action_items,
        "decisions": mt.decisions, "key_topics": mt.key_topics,
        "participants": mt.participants, "duration_mins": mt.duration_mins,
        "sentiment_score": mt.sentiment_score,
        "meeting_date": mt.meeting_date.isoformat() if mt.meeting_date else None,
        "created_at": mt.created_at.isoformat() if mt.created_at else None,
    })


@router.delete("/meeting/{transcript_id}")
async def delete_transcript(
    transcript_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    mt = (await db.execute(
        select(MeetingTranscript).where(MeetingTranscript.id == transcript_id)
    )).scalar_one_or_none()
    if mt and (mt.created_by == current_user.id or
               current_user.role in (UserRole.super_admin, UserRole.admin)):
        await db.delete(mt)
        await db.commit()
    return JSONResponse({"status": "deleted"})