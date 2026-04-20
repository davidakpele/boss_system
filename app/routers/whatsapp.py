# app/routers/whatsapp.py
"""
WhatsApp Business API Integration
──────────────────────────────────
GET  /whatsapp/webhook          — Meta webhook verification
POST /whatsapp/webhook          — Receive inbound messages
POST /whatsapp/send             — Manual send from BOSS dashboard
GET  /whatsapp                  — Dashboard page
GET  /whatsapp/contacts         — All contacts JSON
GET  /whatsapp/contacts/{id}    — Contact + message history
POST /whatsapp/contacts/{id}/block  — Block a contact
POST /whatsapp/contacts/{id}/note   — Add CRM note
GET  /whatsapp/stats            — JSON stats for dashboard
"""

import json
import logging
import re
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.database import get_db, AsyncSessionLocal
from app.models import (
    User, WhatsAppContact, WhatsAppMessage, WhatsAppSession,
    AccountingRecord, TransactionType, KnowledgeChunk
)
from app.auth import require_user
from app.services.ai_service import ai_service
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
templates = Jinja2Templates(directory="app/templates")


async def send_whatsapp_message(to: str, text: str = None, wa_message_id: str = None, use_template: bool = False):
    if use_template:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": "hello_world",
                "language": {"code": "en_US"}
            }
        }
    else:
        # Updated to match your desired format
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {
                "body": text
            }
        }

    if wa_message_id and not use_template:
        payload["context"] = {"message_id": wa_message_id}

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(settings.whatsapp_api_url, json=payload, headers=headers)
            data = resp.json()
            if resp.status_code != 200:
                logger.error(f"WhatsApp API error {resp.status_code}: {data}")
            return data
    except Exception as e:
        logger.error(f"WhatsApp send error: {e}")
        return {"error": str(e)}
    
    
async def mark_message_read(wa_message_id: str):
    """Mark a message as read (shows blue ticks to sender)."""
    if not settings.whatsapp_enabled:
        return
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": wa_message_id,
    }
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(settings.whatsapp_api_url, json=payload, headers=headers)
    except Exception as e:
        logger.warning(f"Mark-read error: {e}")

def detect_intent(text: str) -> str:
    """Quick rule-based intent detection before handing to AI."""
    text_lower = text.lower()

    accounting_kw = [
        "paid", "payment", "expense", "spent", "bought", "purchased",
        "received", "income", "salary", "transport", "cost", "invoice",
        "revenue", "sold", "sale", "record", "log", "naira", "dollar", "₦", "$",
    ]
    inventory_kw = [
        "stock", "inventory", "items", "quantity", "reorder", "product",
        "units", "warehouse", "shelf", "out of stock", "low stock",
    ]
    hr_kw = [
        "hire", "applicant", "cv", "resume", "interview", "candidate",
        "job", "vacancy", "recruit", "employee", "staff", "leave request",
    ]
    greeting_kw = ["hello", "hi", "hey", "good morning", "good afternoon", "good evening", "start"]

    scores = {
        "accounting": sum(1 for k in accounting_kw if k in text_lower),
        "inventory":  sum(1 for k in inventory_kw  if k in text_lower),
        "hr":         sum(1 for k in hr_kw          if k in text_lower),
        "greeting":   sum(1 for k in greeting_kw    if k in text_lower),
    }
    top = max(scores, key=scores.get)
    return top if scores[top] > 0 else "query"

async def build_ai_reply(
    contact: WhatsAppContact,
    user_text: str,
    intent: str,
    session: WhatsAppSession,
    db: AsyncSession,
) -> tuple[str, dict | None]:
    """
    Returns (reply_text, accounting_record_data | None)
    accounting_record_data is set when the AI parsed a transaction.
    """
    history = session.history or []

    if intent == "greeting":
        name = contact.name or "there"
        return (
            f"Hello {name}! 👋 I'm BOSS, your AI business assistant.\n\n"
            "I can help you with:\n"
            "💰 *Record expenses/income* — just describe what you paid or received\n"
            "📦 *Check inventory* — ask about stock levels\n"
            "❓ *Business questions* — I know all about your company\n\n"
            "What can I help you with today?"
        ), None
        
    if intent == "accounting":
        msgs = [
            {"role": "system", "content": (
                "You are a financial AI. The user has sent a WhatsApp message describing a business transaction.\n"
                "Return ONLY valid JSON:\n"
                '{\n'
                '  "is_transaction": true/false,\n'
                '  "type": "income" or "expense",\n'
                '  "amount": <number>,\n'
                '  "currency": "USD" or local currency detected,\n'
                '  "category": <string>,\n'
                '  "description": <clean one-line description>,\n'
                '  "confirmation": <friendly WhatsApp confirmation message using emojis>\n'
                "}\n"
                "If the message is NOT a clear transaction, set is_transaction: false and omit other fields.\n"
                "Return ONLY JSON."
            )},
            {"role": "user", "content": user_text},
        ]
        raw = await ai_service.chat_complete(msgs)
        try:
            clean = raw.strip().replace("```json","").replace("```","").strip()
            data = json.loads(clean)
            if data.get("is_transaction") and data.get("amount"):
                reply = data.get("confirmation", f"✅ Got it! Recorded your {data['type']} of {data.get('currency','')} {data['amount']}.")
                return reply, data
        except Exception as e:
            logger.warning(f"Accounting parse error: {e}")

    context_chunks = await ai_service.retrieve_context(user_text, db)
    context_text = "\n\n".join(
        c.get("content", "")[:400] for c in context_chunks[:4]
    ) if context_chunks else ""

    system = (
        "You are BOSS, an AI business assistant responding via WhatsApp.\n"
        "RULES:\n"
        "- Keep replies short and WhatsApp-friendly (under 300 words)\n"
        "- Use emojis sparingly for warmth\n"
        "- Use *bold* for important info (WhatsApp markdown)\n"
        "- Never use HTML\n"
        "- If you don't know, say so honestly\n"
        "- For accounting requests you couldn't parse, ask for clarification\n"
    )
    if context_text:
        system += f"\nCOMPANY KNOWLEDGE BASE:\n{context_text}\n"
    system += "\nAnswer based on the knowledge above when relevant."

    messages = [{"role": "system", "content": system}]
    for turn in history[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_text})

    reply = await ai_service.chat_complete(messages)
    if len(reply) > 1600:
        reply = reply[:1580] + "…"

    return reply.strip(), None

@router.get("/webhook")
async def verify_webhook(request: Request):
    """Meta calls this to verify your webhook URL is real."""
    params = dict(request.query_params)
    mode      = params.get("hub.mode")
    token     = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified ✓")
        return PlainTextResponse(challenge)

    logger.warning(f"Webhook verification failed — token mismatch. Got: {token}")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_webhook(request: Request):
    """
    Meta posts every inbound message here.
    We process async — always return 200 immediately so Meta doesn't retry.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "ok"})  
    import asyncio
    asyncio.create_task(_process_webhook(body))
    return JSONResponse({"status": "ok"})


async def _process_webhook(body: dict):
    """Parse the Meta payload and handle each message."""
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})

        if "statuses" in value:
            return

        messages = value.get("messages", [])
        contacts_meta = value.get("contacts", [])

        for msg in messages:
            wa_id   = msg.get("from", "")
            wa_msg_id = msg.get("id", "")
            msg_type = msg.get("type", "text")

            if msg_type == "text":
                content = msg.get("text", {}).get("body", "").strip()
            elif msg_type == "interactive":
                content = (msg.get("interactive", {})
                           .get("button_reply", {})
                           .get("title", ""))
            else:
                content = f"[{msg_type} message]"

            if not content or not wa_id:
                continue

            display_name = next(
                (c.get("profile", {}).get("name") for c in contacts_meta if c.get("wa_id") == wa_id),
                None
            )

            async with AsyncSessionLocal() as db:
                await _handle_inbound(
                    db, wa_id, wa_msg_id, content, display_name, msg_type
                )

    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)

async def _handle_inbound(
    db: AsyncSession,
    wa_id: str,
    wa_msg_id: str,
    content: str,
    display_name: str | None,
    msg_type: str,
):
    """Core logic: find/create contact → AI reply → save → send."""
    import asyncio
    from app.services.knowledge_harvester import harvester

    contact = (await db.execute(
        select(WhatsAppContact).where(WhatsAppContact.wa_id == wa_id)
    )).scalar_one_or_none()

    if not contact:
        contact = WhatsAppContact(
            wa_id=wa_id, phone=wa_id, name=display_name
        )
        db.add(contact)
        await db.flush()
    elif display_name and not contact.name:
        contact.name = display_name

    contact.total_messages = (contact.total_messages or 0) + 1

    if contact.is_blocked:
        await db.commit()
        return

    inbound = WhatsAppMessage(
        contact_id=contact.id,
        wa_message_id=wa_msg_id,
        direction="inbound",
        message_type=msg_type,
        content=content,
        status="received",
    )
    db.add(inbound)
    await db.flush()

    await mark_message_read(wa_msg_id)
    session = (await db.execute(
        select(WhatsAppSession).where(WhatsAppSession.contact_id == contact.id)
    )).scalar_one_or_none()
    if not session:
        session = WhatsAppSession(contact_id=contact.id, history=[])
        db.add(session)
        await db.flush()

    intent = detect_intent(content)
    inbound.intent = intent

    reply, accounting_data = await build_ai_reply(
        contact, content, intent, session, db
    )

    inbound.ai_handled = True
    inbound.ai_response = reply

    if accounting_data and accounting_data.get("is_transaction"):
        try:
            rec = AccountingRecord(
                type=TransactionType(accounting_data["type"]),
                amount=float(accounting_data["amount"]),
                currency=accounting_data.get("currency", "USD"),
                category=accounting_data.get("category", "General"),
                description=accounting_data.get("description", content),
                recorded_by=None,
                ai_parsed=True,
            )
            db.add(rec)
            logger.info(f"Auto-recorded {accounting_data['type']} of {accounting_data['amount']} from WhatsApp")
        except Exception as e:
            logger.error(f"Failed to save accounting record: {e}")

    history = list(session.history or [])
    history.append({"role": "user",      "content": content})
    history.append({"role": "assistant", "content": reply})
    session.history = history[-20:]

    await db.commit()

    # Passive learning — inbound message
    asyncio.create_task(harvester.learn_from_whatsapp_message(
        content      = content,
        direction    = "inbound",
        contact_name = contact.name or contact.phone,
        db           = AsyncSessionLocal(),
    ))

    # Passive learning — outbound AI reply
    asyncio.create_task(harvester.learn_from_whatsapp_message(
        content      = reply,
        direction    = "outbound",
        contact_name = contact.name or contact.phone,
        db           = AsyncSessionLocal(),
    ))

    send_result = await send_whatsapp_message(wa_id, reply, wa_msg_id)

    async with AsyncSessionLocal() as out_db:
        out_msg = WhatsAppMessage(
            contact_id=contact.id,
            wa_message_id=send_result.get("messages", [{}])[0].get("id"),
            direction="outbound",
            message_type="text",
            content=reply,
            status="sent" if "messages" in send_result else "failed",
            ai_handled=True,
            error=str(send_result.get("error", "")) or None,
        )
        out_db.add(out_msg)
        await out_db.commit()

    logger.info(f"WhatsApp: replied to {wa_id} (intent={intent})")

@router.get("", response_class=HTMLResponse)
async def whatsapp_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    total_contacts = (await db.execute(select(func.count(WhatsAppContact.id)))).scalar() or 0
    total_messages = (await db.execute(select(func.count(WhatsAppMessage.id)))).scalar() or 0
    ai_handled     = (await db.execute(
        select(func.count(WhatsAppMessage.id)).where(WhatsAppMessage.ai_handled == True)
    )).scalar() or 0
    today_msgs     = (await db.execute(
        select(func.count(WhatsAppMessage.id))
        .where(WhatsAppMessage.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0))
    )).scalar() or 0

    contacts = (await db.execute(
        select(WhatsAppContact).order_by(WhatsAppContact.last_seen.desc().nullslast(), WhatsAppContact.first_seen.desc()).limit(20)
    )).scalars().all()

    return templates.TemplateResponse(request=request, name="whatsapp/dashboard.html", context={
        "user": current_user, "page": "whatsapp",
        "total_contacts": total_contacts,
        "total_messages": total_messages,
        "ai_handled": ai_handled,
        "today_msgs": today_msgs,
        "contacts": contacts,
        "wa_enabled": settings.whatsapp_enabled,
        "wa_number": settings.WHATSAPP_PHONE_NUMBER_ID,
    })

@router.get("/contacts")
async def list_contacts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    contacts = (await db.execute(
        select(WhatsAppContact).order_by(WhatsAppContact.last_seen.desc().nullslast()).limit(100)
    )).scalars().all()
    return JSONResponse([{
        "id": c.id, "wa_id": c.wa_id, "name": c.name, "phone": c.phone,
        "total_messages": c.total_messages, "is_blocked": c.is_blocked,
        "first_seen": c.first_seen.isoformat() if c.first_seen else None,
    } for c in contacts])


@router.get("/contacts/{contact_id}/history")
async def contact_history(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    msgs = (await db.execute(
        select(WhatsAppMessage)
        .where(WhatsAppMessage.contact_id == contact_id)
        .order_by(WhatsAppMessage.created_at.asc()).limit(100)
    )).scalars().all()
    return JSONResponse([{
        "id": m.id, "direction": m.direction, "content": m.content,
        "status": m.status, "ai_handled": m.ai_handled,
        "intent": m.intent,
        "created_at": m.created_at.isoformat() if m.created_at else "",
    } for m in msgs])

@router.post("/contacts/{contact_id}/block")
async def block_contact(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    c = (await db.execute(select(WhatsAppContact).where(WhatsAppContact.id == contact_id))).scalar_one_or_none()
    if c:
        c.is_blocked = not c.is_blocked
        await db.commit()
    return JSONResponse({"is_blocked": c.is_blocked if c else False})

@router.post("/contacts/{contact_id}/note")
async def add_note(
    contact_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
    ):
    body = await request.json()
    note = (body.get("note") or "").strip()
    c = (await db.execute(select(WhatsAppContact).where(WhatsAppContact.id == contact_id))).scalar_one_or_none()
    if c and note:
        c.notes = note
        await db.commit()
    return JSONResponse({"status": "saved"})

@router.post("/send")
async def manual_send(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    """Send a message manually from the BOSS dashboard."""
    body = await request.json()
    to      = (body.get("to") or "").strip().replace("+", "").replace(" ", "")
    message = (body.get("message") or "").strip()

    if not to or not message:
        return JSONResponse({"error": "to and message are required"}, status_code=400)
    if not settings.whatsapp_enabled:
        return JSONResponse({"error": "WhatsApp not configured"}, status_code=503)

    result = await send_whatsapp_message(to, message, use_template=False)
    
    if "messages" in result:
        contact = (await db.execute(
            select(WhatsAppContact).where(WhatsAppContact.wa_id == to)
        )).scalar_one_or_none()
        if not contact:
            contact = WhatsAppContact(wa_id=to, phone=to)
            db.add(contact)
            await db.flush()
        db.add(WhatsAppMessage(
            contact_id=contact.id,
            wa_message_id=result["messages"][0]["id"],
            direction="outbound", message_type="text",
            content=message, status="sent", ai_handled=False,
        ))
        await db.commit()
        return JSONResponse(content=result)
    else:
        return JSONResponse(content=result, status_code=500)
    

@router.get("/stats")
async def wa_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    since = datetime.utcnow() - timedelta(days=7)
    rows = (await db.execute(
        select(
            func.date(WhatsAppMessage.created_at).label("day"),
            func.count(WhatsAppMessage.id).label("count"),
        )
        .where(WhatsAppMessage.created_at >= since)
        .group_by(func.date(WhatsAppMessage.created_at))
        .order_by(func.date(WhatsAppMessage.created_at))
    )).all()
    return JSONResponse({
        "labels": [str(r.day) for r in rows],
        "values": [r.count for r in rows],
    })
    
@router.get("/token-status")
async def token_status(
    current_user: User = Depends(require_user),
):
    """Check if the current WhatsApp token is still valid."""
    if not settings.whatsapp_enabled:
        return JSONResponse({"valid": False, "reason": "WhatsApp not configured in .env"})
 
    url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=headers)
            data = r.json()
        if r.status_code == 200:
            return JSONResponse({"valid": True, "phone_id": data.get("id"), "display": data.get("display_phone_number")})
        else:
            err = data.get("error", {})
            return JSONResponse({"valid": False, "reason": err.get("message", "Unknown error"), "code": err.get("code")})
    except Exception as e:
        return JSONResponse({"valid": False, "reason": str(e)})
 
 
@router.post("/update-token")
async def update_token(
    request: Request,
    current_user: User = Depends(require_user),
):
    """
    Update the WhatsApp access token at runtime without restarting the server.
    Also writes it to .env so it persists on restart.
    Only super_admin can do this.
    """
    from app.models import UserRole
    if current_user.role not in (UserRole.super_admin, UserRole.admin):
        raise HTTPException(status_code=403)
 
    body = await request.json()
    new_token = (body.get("token") or "").strip()
    if not new_token or len(new_token) < 50:
        return JSONResponse({"error": "Token looks too short — paste the full token"}, status_code=400)
 
    url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}"
    headers = {"Authorization": f"Bearer {new_token}"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                err = r.json().get("error", {})
                return JSONResponse({"error": f"Token invalid: {err.get('message','Unknown')}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Could not verify token: {e}"}, status_code=400)
    settings.WHATSAPP_ACCESS_TOKEN = new_token

    try:
        env_path = ".env"
        with open(env_path, "r") as f:
            lines = f.readlines()
 
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith("WHATSAPP_ACCESS_TOKEN="):
                new_lines.append(f"WHATSAPP_ACCESS_TOKEN={new_token}\n")
                updated = True
            else:
                new_lines.append(line)
 
        if not updated:
            new_lines.append(f"\nWHATSAPP_ACCESS_TOKEN={new_token}\n")
 
        with open(env_path, "w") as f:
            f.writelines(new_lines)
 
        return JSONResponse({"status": "updated", "message": "Token updated and saved to .env ✓"})
    except Exception as e:
        return JSONResponse({"status": "updated_memory_only", "message": f"Token active now but .env write failed: {e}"})
    
    