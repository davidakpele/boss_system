"""
BOSS System — WhatsApp Auto-Response Integration
File: app/routers/whatsapp.py

Drop this file into your app/routers/ directory.
"""

import logging
import httpx
import asyncio
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])

# ──────────────────────────────────────────────
# Config (add these to your .env + settings)
# ──────────────────────────────────────────────
WHATSAPP_TOKEN = settings.WHATSAPP_TOKEN          # Meta access token
WHATSAPP_PHONE_NUMBER_ID = settings.WHATSAPP_PHONE_NUMBER_ID  # 1082779354917692
WHATSAPP_VERIFY_TOKEN = settings.WHATSAPP_VERIFY_TOKEN        # your chosen secret
WHATSAPP_API_URL = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

# ──────────────────────────────────────────────
# 1. Webhook Verification (GET)
# Meta calls this once when you register the webhook
# ──────────────────────────────────────────────
@router.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("✅ WhatsApp webhook verified successfully")
        return int(challenge)

    raise HTTPException(status_code=403, detail="Webhook verification failed")


# ──────────────────────────────────────────────
# 2. Receive Messages (POST)
# Meta sends every incoming client message here
# ──────────────────────────────────────────────
@router.post("/webhook")
async def receive_message(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        body = await request.json()
        logger.info(f"📩 WhatsApp webhook received: {body}")

        entry = body.get("entry", [])
        if not entry:
            return {"status": "no_entry"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "no_changes"}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])

        if not messages:
            # Could be a status update (read/delivered) — ignore
            return {"status": "ok"}

        message = messages[0]
        from_number = message.get("from")           # e.g. "2348012345678"
        msg_type = message.get("type")
        timestamp = message.get("timestamp")

        # Only handle text messages for now
        if msg_type != "text":
            await send_whatsapp_message(
                to=from_number,
                text="Hello! I can only respond to text messages at the moment. Please type your question."
            )
            return {"status": "non_text_handled"}

        client_text = message["text"]["body"]
        logger.info(f"📨 Message from {from_number}: {client_text}")

        # Log to DB asynchronously
        asyncio.create_task(log_whatsapp_message(db, from_number, client_text, "incoming"))

        # Generate AI response using your existing Ollama/RAG service
        ai_reply = await generate_boss_reply(client_text, from_number, db)

        # Send reply back to WhatsApp
        await send_whatsapp_message(to=from_number, text=ai_reply)

        # Log outgoing reply
        asyncio.create_task(log_whatsapp_message(db, from_number, ai_reply, "outgoing"))

        return {"status": "replied"}

    except Exception as e:
        logger.error(f"❌ WhatsApp webhook error: {e}", exc_info=True)
        return {"status": "error", "detail": str(e)}


# ──────────────────────────────────────────────
# 3. Send a WhatsApp Message
# ──────────────────────────────────────────────
async def send_whatsapp_message(to: str, text: str):
    """Send a text message to a WhatsApp number via Meta API."""
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text[:4096]},  # WhatsApp 4096 char limit
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(WHATSAPP_API_URL, json=payload, headers=headers)
        if response.status_code != 200:
            logger.error(f"❌ WhatsApp send failed: {response.status_code} {response.text}")
        else:
            logger.info(f"✅ WhatsApp reply sent to {to}")
        return response


# ──────────────────────────────────────────────
# 4. AI Reply Generation
# Reuses your existing Ask BOSS / Ollama RAG logic
# ──────────────────────────────────────────────
async def generate_boss_reply(user_message: str, from_number: str, db: AsyncSession) -> str:
    """
    Generate an AI reply by querying your BOSS knowledge base (RAG).
    This mirrors your existing Ask BOSS flow.
    """
    try:
        # Step 1: Check business hours (optional — customize as needed)
        now = datetime.now()
        if now.hour < 8 or now.hour >= 18 or now.weekday() >= 5:
            return (
                "Thank you for reaching out! 🌙\n\n"
                "Our business hours are Monday–Friday, 8am–6pm.\n"
                "Your message has been recorded and we'll get back to you shortly.\n\n"
                "— BOSS Auto-Response"
            )

        # Step 2: Search your knowledge base (vector RAG)
        # Import your existing AI service
        from app.services.ai_service import query_knowledge_base, call_ollama

        context_chunks = await query_knowledge_base(
            db=db,
            query=user_message,
            top_k=5,
            access_level="all_staff",
        )

        if context_chunks:
            context_text = "\n\n".join([c["content"] for c in context_chunks])
            prompt = f"""You are BOSS, an intelligent business assistant. A client has contacted us via WhatsApp.

Client message: {user_message}

Relevant company information:
{context_text}

Reply professionally and concisely in under 200 words. If you cannot answer from the context, say so politely and offer to connect them with a team member."""
        else:
            prompt = f"""You are BOSS, an intelligent business assistant for a company. A client sent this WhatsApp message:

"{user_message}"

You have no specific company knowledge for this query. Respond professionally, acknowledge their message, and offer to connect them with a team member. Keep it under 100 words."""

        reply = await call_ollama(prompt)
        return reply.strip()

    except Exception as e:
        logger.error(f"❌ AI reply generation failed: {e}", exc_info=True)
        return (
            "Thank you for your message! 👋\n\n"
            "One of our team members will get back to you shortly.\n\n"
            "— BOSS System"
        )


# ──────────────────────────────────────────────
# 5. Log WhatsApp Messages to Database
# ──────────────────────────────────────────────
async def log_whatsapp_message(db: AsyncSession, phone: str, content: str, direction: str):
    """
    Log WhatsApp conversations to the DB.
    Uses a simple whatsapp_logs table (see migration below).
    """
    try:
        await db.execute(
            text("""
                INSERT INTO whatsapp_logs (phone_number, direction, content, created_at)
                VALUES (:phone, :direction, :content, NOW())
            """),
            {"phone": phone, "direction": direction, "content": content}
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"Could not log WhatsApp message: {e}")


# ──────────────────────────────────────────────
# 6. Optional: Admin endpoint to send manual messages
# Useful for staff to reply to clients from BOSS dashboard
# ──────────────────────────────────────────────
@router.post("/send")
async def manual_send(payload: dict):
    """
    Send a manual WhatsApp message from the BOSS dashboard.
    POST /whatsapp/send  { "to": "2348012345678", "message": "Hello!" }
    """
    to = payload.get("to")
    message = payload.get("message")
    if not to or not message:
        raise HTTPException(status_code=400, detail="'to' and 'message' are required")

    response = await send_whatsapp_message(to=to, text=message)
    return {"status": "sent", "to": to}