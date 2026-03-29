import httpx
import json
from typing import List, Optional, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from app.config import settings
from app.models import KnowledgeChunk, Document, AIConversation, AIMessage, AccessLevel
import asyncio
import logging

logger = logging.getLogger(__name__)


class AIService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL

    async def check_ollama_health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def retrieve_context(
        self,
        query: str,
        db: AsyncSession,
        user_role: str = "staff",
        department: Optional[str] = None,
        max_chunks: int = 5,
    ) -> List[dict]:
        """Simple keyword-based retrieval from knowledge base."""
        keywords = [w.lower() for w in query.split() if len(w) > 3]
        if not keywords:
            keywords = query.lower().split()

        # Build access filter
        access_filter = [KnowledgeChunk.document_id == None]  # noqa: E711 - message chunks always accessible

        if user_role in ("super_admin", "admin", "manager"):
            access_levels = [AccessLevel.all_staff, AccessLevel.restricted, AccessLevel.confidential]
        elif user_role == "staff":
            access_levels = [AccessLevel.all_staff, AccessLevel.restricted]
        else:
            access_levels = [AccessLevel.all_staff]

        # Get chunks from knowledge base
        stmt = select(KnowledgeChunk).limit(100)
        result = await db.execute(stmt)
        chunks = result.scalars().all()

        # Score chunks by keyword match
        scored = []
        for chunk in chunks:
            text = (chunk.content or "").lower() + " " + (chunk.summary or "").lower()
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_chunks = scored[:max_chunks]

        return [
            {
                "content": c.content[:800],
                "source": c.source_type,
                "summary": c.summary or "",
                "score": s,
            }
            for s, c in top_chunks
        ]

    async def build_prompt(
        self,
        user_message: str,
        history: List[dict],
        context_chunks: List[dict],
        system_context: str = "",
    ) -> List[dict]:
        """Build messages array for Ollama."""
        system_msg = (
            "You are BOSS (Business Operating System), an intelligent AI assistant for a corporate organization. "
            "You help employees with company policies, procedures, knowledge, and operations. "
            "Be professional, concise, and helpful. Always base your answers on the provided company knowledge. "
            "If you don't have enough information, say so clearly.\n\n"
        )

        if context_chunks:
            system_msg += "RELEVANT COMPANY KNOWLEDGE:\n"
            for i, chunk in enumerate(context_chunks, 1):
                system_msg += f"[{i}] {chunk['content']}\n\n"

        if system_context:
            system_msg += f"\nADDITIONAL CONTEXT:\n{system_context}\n"

        messages = [{"role": "system", "content": system_msg}]

        # Add history (last 10 turns)
        for msg in history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": user_message})
        return messages

    async def chat_stream(
        self,
        messages: List[dict],
    ) -> AsyncGenerator[str, None]:
        """Stream response from Ollama."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 1024,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                ) as response:
                    async for line in response.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                if "message" in data and "content" in data["message"]:
                                    yield data["message"]["content"]
                                if data.get("done"):
                                    break
                            except json.JSONDecodeError:
                                continue
        except httpx.ConnectError:
            yield "\n\n⚠️ AI service is not available. Please ensure Ollama is running with the model loaded."
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            yield f"\n\n⚠️ Error connecting to AI service: {str(e)}"

    async def chat_complete(self, messages: List[dict]) -> str:
        """Non-streaming chat completion."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 512},
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                data = resp.json()
                return data.get("message", {}).get("content", "")
        except Exception as e:
            logger.error(f"Ollama complete error: {e}")
            return ""

    async def extract_knowledge_from_message(self, message: str, db: AsyncSession) -> Optional[str]:
        """Extract key business knowledge from chat messages."""
        if len(message) < 50:
            return None

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a knowledge extraction AI. Analyze the following business conversation message "
                    "and determine if it contains valuable business knowledge (sales experiences, customer insights, "
                    "operational knowledge, process knowledge, etc.). "
                    "If it does, extract a concise knowledge summary (2-3 sentences). "
                    "If it doesn't contain useful business knowledge, respond with 'NO_KNOWLEDGE'. "
                    "Respond ONLY with the knowledge summary or 'NO_KNOWLEDGE'."
                ),
            },
            {"role": "user", "content": f"Message: {message}"},
        ]

        result = await self.chat_complete(messages)
        if result and "NO_KNOWLEDGE" not in result and len(result) > 20:
            return result
        return None

    async def extract_compliance_from_document(self, content: str) -> List[dict]:
        """Extract compliance requirements from a document."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a compliance analysis AI. Extract regulatory and compliance requirements from documents. "
                    "Return a JSON array of objects with: regulation_type, requirement, risk_level (low/medium/high/critical). "
                    "Return ONLY valid JSON, no other text."
                ),
            },
            {
                "role": "user",
                "content": f"Extract compliance requirements from:\n\n{content[:3000]}",
            },
        ]
        result = await self.chat_complete(messages)
        try:
            # Clean potential markdown
            clean = result.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    async def summarize_text(self, text: str) -> str:
        """Generate a short summary of text."""
        messages = [
            {
                "role": "system",
                "content": "Summarize the following text in 1-2 sentences for a business knowledge base. Be concise.",
            },
            {"role": "user", "content": text[:2000]},
        ]
        return await self.chat_complete(messages)


ai_service = AIService()
