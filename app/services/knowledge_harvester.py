# app/services/knowledge_harvester.py
"""
Passive Knowledge Harvester
────────────────────────────
Learns from all BOSS communication channels automatically:
  - Outbound email campaigns (deduplicated by content hash)
  - Internal messages (channels)
  - WhatsApp conversations
  - AI conversations (Ask BOSS Q&A)
  - Documents (already handled by documents.py)

De-duplication: a SHA-256 hash of the normalised content is stored
on every KnowledgeChunk. If the same content arrives again (e.g. the
same email body sent to 2,000 recipients), only one chunk is saved.

Usage:
  from app.services.knowledge_harvester import harvester
  await harvester.learn_from_email(campaign, db)
  await harvester.learn_from_message(message_content, channel_name, db)
  await harvester.learn_from_whatsapp(wa_message, db)
"""

import hashlib
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import KnowledgeChunk
from app.services.ai_service import ai_service
from app.services.document_service import chunk_text

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _content_hash(text: str) -> str:
    """SHA-256 of lowercased, whitespace-normalised text."""
    normalised = re.sub(r'\s+', ' ', text.lower().strip())
    return hashlib.sha256(normalised.encode()).hexdigest()[:16]   # 16 hex chars is enough


def _clean_html(html: str) -> str:
    """Strip HTML tags and decode basic entities."""
    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&') \
               .replace('&lt;', '<').replace('&gt;', '>')  \
               .replace('&quot;', '"').replace('&#39;', "'")
    return re.sub(r'\s+', ' ', text).strip()


async def _already_stored(content_hash: str, db: AsyncSession) -> bool:
    from sqlalchemy import cast, type_coerce
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import func, Text
    existing = (await db.execute(
        select(KnowledgeChunk).where(
            func.cast(KnowledgeChunk.keywords, Text).contains(content_hash)
        )
    )).scalar_one_or_none()
    return existing is not None


async def _store_chunks(
    content: str,
    source_type: str,
    department: str,
    db: AsyncSession,
    label: str = "",
    min_words: int = 30,
    tenant_id: int = None, 
) -> int:
    """
    Chunk content, deduplicate, summarise, and store.
    Returns the number of NEW chunks stored.
    """
    if not content or len(content.split()) < min_words:
        return 0

    chunks = chunk_text(content, chunk_size=400, overlap=50)
    stored = 0

    for ct in chunks[:25]:          # cap at 25 chunks per source
        if len(ct.split()) < min_words:
            continue

        ch_hash = _content_hash(ct)
        if await _already_stored(ch_hash, db):
            continue                # exact duplicate — skip

        try:
            summary = await ai_service.summarize_text(ct)
        except Exception:
            summary = ct[:200]

        kc = KnowledgeChunk(
            source_type = source_type,
            content     = ct,
            summary     = summary,
            department  = department,
            keywords    = [{"hash": ch_hash}, {"label": label}],
            tenant_id   = tenant_id,
        )
        db.add(kc)
        await db.flush()

        # Background embedding (fire-and-forget)
        try:
            emb = await ai_service.embed_and_store_chunk(ct)
            if emb:
                kc.embedding = emb
        except Exception:
            pass

        stored += 1

    if stored:
        await db.commit()
        logger.info(f"Harvested {stored} new chunks from {source_type} [{label}]")

    return stored


# ── Main Harvester Class ──────────────────────────────────────────────────────

class KnowledgeHarvester:

    # ── Email Campaigns ───────────────────────────────────────────────────────

    async def learn_from_email_campaign(self, campaign, db: AsyncSession, tenant_id: int = None) -> int:
        """
        Learn from a sent email campaign body.
        Called once after a campaign is delivered.
        Strips HTML, deduplicates, stores as source_type='email_campaign'.
        """
        body = campaign.html_body or campaign.text_body or ""
        if not body:
            return 0

        plain = _clean_html(body) if '<' in body else body
        label = f"campaign:{campaign.id}:{campaign.name[:40]}"

        return await _store_chunks(
            content     = plain,
            source_type = "email_campaign",
            department  = "General",
            db          = db,
            label       = label,
            tenant_id   = tenant_id,
        )
        
    async def learn_from_message(
        self,
        content: str,
        channel_name: str,
        department: str,
        db: AsyncSession,
        tenant_id: int = None, 
    ) -> int:
        """
        Learn from a single channel message.
        Only stores if it's long enough to be genuinely useful (>40 words).
        Short messages like "ok", "thanks", "see you at 3" are ignored.
        """
        if not content:
            return 0

        plain = content.strip()
        words = plain.split()

        # Skip short, conversational messages
        if len(words) < 40:
            return 0

        return await _store_chunks(
            content     = plain,
            source_type = "message",
            department  = department or "General",
            db          = db,
            label       = f"channel:{channel_name}",
            min_words   = 40,
            tenant_id   = tenant_id,
        )

    async def learn_from_channel_batch(
        self,
        messages: list[dict], 
        db: AsyncSession,
    ) -> int:
        """
        Batch-learn from a list of messages.
        Called by the nightly harvester job or manually by an admin.
        """
        total = 0
        for m in messages:
            n = await self.learn_from_message(
                content      = m.get("content", ""),
                channel_name = m.get("channel_name", ""),
                department   = m.get("department", "General"),
                db           = db,
            )
            total += n
        return total

    # ── WhatsApp ──────────────────────────────────────────────────────────────

    async def learn_from_whatsapp_message(
        self,
        content: str,
        direction: str,         # "inbound" | "outbound"
        contact_name: str,
        db: AsyncSession,
        tenant_id: int = None,
    ) -> int:
        """
        Learn from a WhatsApp message.
        Inbound = customer asks something → useful for FAQ knowledge.
        Outbound = business replies → useful for how the company responds.
        """
        if not content or len(content.split()) < 20:
            return 0

        label = f"whatsapp:{direction}:{contact_name[:30]}"
        return await _store_chunks(
            content     = content.strip(),
            source_type = "whatsapp",
            department  = "General",
            db          = db,
            label       = label,
            min_words   = 20,
            tenant_id   = tenant_id,
        )

    # ── AI Conversations ──────────────────────────────────────────────────────

    async def learn_from_ai_conversation(
        self,
        question: str,
        answer: str,
        db: AsyncSession,
        tenant_id: int = None,
    ) -> int:
        """
        Learn from Ask BOSS conversations.
        If the AI gave a confident answer, store the Q+A pair as knowledge.
        This means the AI builds on its own good answers over time.
        """
        if not question or not answer:
            return 0

        # Skip answers that indicate the AI didn't know
        uncertainty_phrases = [
            "i don't know", "i'm not sure", "no information",
            "not found", "cannot find", "i cannot", "i'm unable",
        ]
        if any(p in answer.lower() for p in uncertainty_phrases):
            return 0

        combined = f"Q: {question.strip()}\n\nA: {answer.strip()}"

        return await _store_chunks(
            content     = combined,
            source_type = "ai_qa",
            department  = "General",
            db          = db,
            label       = "ask_boss",
            min_words   = 30,
            tenant_id   = tenant_id,
        )

    # ── Bulk / Nightly Harvest ────────────────────────────────────────────────

    async def run_full_harvest(self, db: AsyncSession) -> dict:
        """
        Full harvest pass — picks up everything not yet learned.
        Run nightly or triggered manually from the admin panel.
        Returns a summary dict of what was harvested.
        """
        from app.models import (
            Message, WhatsAppMessage, EmailCampaign, AIMessage, Channel
        )
        from sqlalchemy import select, and_

        results = {
            "messages":     0,
            "whatsapp":     0,
            "email":        0,
            "ai_qa":        0,
            "total":        0,
        }

        # ── 1. Messages (last 7 days of substantive messages) ─────────────────
        from datetime import timedelta
        since = datetime.utcnow() - timedelta(days=7)

        msgs = (await db.execute(
            select(Message, Channel.name, Channel.department)
            .join(Channel, Message.channel_id == Channel.id)
            .where(
                Message.is_deleted == False,
                Message.created_at >= since,
                Message.message_type == "text",
                Message.content != None,
            )
            .order_by(Message.created_at.desc())
            .limit(500)
        )).all()

        for msg, ch_name, dept in msgs:
            n = await self.learn_from_message(
                content      = msg.content or "",
                channel_name = ch_name or "",
                department   = dept or "General",
                db           = db,
            )
            results["messages"] += n

        # ── 2. WhatsApp messages ──────────────────────────────────────────────
        wa_msgs = (await db.execute(
            select(WhatsAppMessage)
            .where(
                WhatsAppMessage.content != None,
                WhatsAppMessage.created_at >= since,
            )
            .order_by(WhatsAppMessage.created_at.desc())
            .limit(300)
        )).scalars().all()

        for wm in wa_msgs:
            n = await self.learn_from_whatsapp_message(
                content      = wm.content or "",
                direction    = wm.direction or "inbound",
                contact_name = str(wm.contact_id),
                db           = db,
            )
            results["whatsapp"] += n
        campaigns = (await db.execute(
            select(EmailCampaign).where(EmailCampaign.status.in_(["sent", "paused"]))
            .order_by(EmailCampaign.created_at.desc())
            .limit(50)
        )).scalars().all()

        for campaign in campaigns:
            n = await self.learn_from_email_campaign(campaign, db)
            results["email"] += n
        from app.models import AIConversation

        ai_msgs = (await db.execute(
            select(AIMessage)
            .where(AIMessage.role == "assistant", AIMessage.created_at >= since)
            .order_by(AIMessage.created_at.desc())
            .limit(200)
        )).scalars().all()
        for ai_msg in ai_msgs:
            user_msg = (await db.execute(
                select(AIMessage)
                .where(
                    AIMessage.conversation_id == ai_msg.conversation_id,
                    AIMessage.role == "user",
                    AIMessage.id < ai_msg.id,
                )
                .order_by(AIMessage.id.desc())
                .limit(1)
            )).scalar_one_or_none()

            if user_msg:
                n = await self.learn_from_ai_conversation(
                    question = user_msg.content,
                    answer   = ai_msg.content,
                    db       = db,
                )
                results["ai_qa"] += n

        results["total"] = sum(v for k, v in results.items() if k != "total")
        logger.info(f"Full harvest complete: {results}")
        return results


harvester = KnowledgeHarvester()