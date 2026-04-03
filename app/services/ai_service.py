# app/services/ai_service.py
import httpx
import json
import numpy as np
from typing import List, Optional, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from app.config import settings
from app.models import KnowledgeChunk, Document, AIConversation, AIMessage, AccessLevel, RiskItem
import logging

logger = logging.getLogger(__name__)

GREETING_TRIGGERS = {"hello", "hi", "hey", "thanks", "thank you", "ok", "okay", "sure", "great", "cool", "yes", "no", "alright"}

class AIService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL
        self._embedder = None   # lazy-loaded

    # ──────────────────────────────────────────────
    #  EMBEDDING MODEL  (sentence-transformers)
    # ──────────────────────────────────────────────
    def _get_embedder(self):
        """Lazy-load the embedding model so startup is fast."""
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
                logger.info("Embedding model loaded: all-MiniLM-L6-v2")
            except Exception as e:
                logger.warning(f"Could not load embedding model: {e}. Falling back to keyword search.")
        return self._embedder

    def embed(self, text: str) -> Optional[List[float]]:
        """Return a 384-dim embedding vector or None if unavailable."""
        embedder = self._get_embedder()
        if not embedder:
            return None
        try:
            vec = embedder.encode(text, convert_to_numpy=True)
            return vec.tolist()
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return None

    # ──────────────────────────────────────────────
    #  HEALTH CHECK
    # ──────────────────────────────────────────────
    async def check_ollama_health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    # ──────────────────────────────────────────────
    #  RETRIEVAL  (vector-first, keyword fallback)
    # ──────────────────────────────────────────────
    async def retrieve_context(
        self,
        query: str,
        db: AsyncSession,
        user_role: str = "staff",
        department: Optional[str] = None,
        max_chunks: int = 5,
    ) -> List[dict]:
        """
        Retrieve the most relevant knowledge chunks.
        Uses cosine-similarity on stored embeddings when available;
        falls back to keyword scoring otherwise.
        Returns chunks with a 'chunk_id' field for citation linking.
        """
        # Role-based access
        if user_role in ("super_admin", "admin", "manager"):
            allowed_levels = [AccessLevel.all_staff, AccessLevel.restricted, AccessLevel.confidential]
        elif user_role == "staff":
            allowed_levels = [AccessLevel.all_staff, AccessLevel.restricted]
        else:
            allowed_levels = [AccessLevel.all_staff]

        # Fetch chunks (limit to 200 for scoring)
        stmt = select(KnowledgeChunk).limit(200)
        chunks = (await db.execute(stmt)).scalars().all()

        if not chunks:
            return []

        query_vec = self.embed(query)

        if query_vec is not None:
            # ── Vector similarity ──
            q = np.array(query_vec)
            scored = []
            for chunk in chunks:
                if chunk.embedding:
                    try:
                        cv = np.array(json.loads(chunk.embedding))
                        # cosine similarity
                        denom = (np.linalg.norm(q) * np.linalg.norm(cv))
                        sim = float(np.dot(q, cv) / denom) if denom > 0 else 0.0
                        scored.append((sim, chunk))
                    except Exception:
                        pass
            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[:max_chunks]
        else:
            # ── Keyword fallback ──
            keywords = [w.lower() for w in query.split() if len(w) > 3] or query.lower().split()
            scored = []
            for chunk in chunks:
                text_body = (chunk.content or "").lower() + " " + (chunk.summary or "").lower()
                score = sum(1 for kw in keywords if kw in text_body)
                if score > 0:
                    scored.append((score, chunk))
            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[:max_chunks]

        return [
            {
                "chunk_id": c.id,
                "document_id": c.document_id,
                "content": c.content[:800],
                "source": c.source_type,
                "summary": c.summary or "",
                "score": round(s, 4),
                "department": c.department or "",
            }
            for s, c in top
        ]

    # ──────────────────────────────────────────────
    #  PROMPT BUILDER
    # ──────────────────────────────────────────────
    async def build_prompt(
        self,
        user_message: str,
        history: List[dict],
        context_chunks: List[dict],
        system_context: str = "",
    ) -> List[dict]:
        system_msg = (
            "You are BOSS (Business Operating System), an intelligent AI assistant for a corporate organization. "
            "You help employees with company policies, procedures, knowledge, and operations. "
            "Be professional, concise, and helpful. "
            "Always base your answers on the provided company knowledge. "
            "When you use information from the knowledge base, reference it like [1], [2], etc. "
            "If you don't have enough information, say so clearly.\n\n"
        )
        if context_chunks:
            system_msg += "RELEVANT COMPANY KNOWLEDGE:\n"
            for i, chunk in enumerate(context_chunks, 1):
                src = f"[Source: {chunk['source']}]"
                system_msg += f"[{i}] {src}\n{chunk['content']}\n\n"
        if system_context:
            system_msg += f"\nADDITIONAL CONTEXT:\n{system_context}\n"

        messages = [{"role": "system", "content": system_msg}]
        for msg in history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})
        return messages

    # ──────────────────────────────────────────────
    #  STREAMING CHAT
    # ──────────────────────────────────────────────
    async def chat_stream(self, messages: List[dict]) -> AsyncGenerator[str, None]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.7, "top_p": 0.9, "num_predict": 1024},
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
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
            yield "\n\n⚠️ AI service unavailable. Ensure Ollama is running."
        except Exception as e:
            logger.error(f"Ollama stream error: {e}")
            yield f"\n\n⚠️ Error: {str(e)}"

    async def chat_complete(self, messages: List[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 512},
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                return resp.json().get("message", {}).get("content", "")
        except Exception as e:
            logger.error(f"Ollama complete error: {e}")
            return ""

    # ──────────────────────────────────────────────
    #  KNOWLEDGE EXTRACTION FROM CHAT
    # ──────────────────────────────────────────────
    async def extract_knowledge_from_message(self, message: str, db: AsyncSession) -> Optional[str]:
        if len(message) < 50:
            return None
        msgs = [
            {
                "role": "system",
                "content": (
                    "You are a knowledge extraction AI. Analyze this business message. "
                    "If it contains valuable business knowledge (sales insights, customer info, process knowledge), "
                    "extract a concise 2-3 sentence summary. "
                    "If not useful, respond ONLY with 'NO_KNOWLEDGE'."
                ),
            },
            {"role": "user", "content": f"Message: {message}"},
        ]
        result = await self.chat_complete(msgs)
        if result and "NO_KNOWLEDGE" not in result and len(result) > 20:
            return result
        return None

    # ──────────────────────────────────────────────
    #  COMPLIANCE EXTRACTION
    # ──────────────────────────────────────────────
    async def extract_compliance_from_document(self, content: str) -> List[dict]:
        msgs = [
            {
                "role": "system",
                "content": (
                    "You are a compliance analysis AI. Extract regulatory requirements from documents. "
                    "Return a JSON array with objects having: regulation_type, requirement, risk_level (low/medium/high/critical). "
                    "Return ONLY valid JSON, no other text."
                ),
            },
            {"role": "user", "content": f"Extract compliance requirements from:\n\n{content[:3000]}"},
        ]
        result = await self.chat_complete(msgs)
        try:
            clean = result.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    # ──────────────────────────────────────────────
    #  SUMMARIZE TEXT
    # ──────────────────────────────────────────────
    async def summarize_text(self, text: str) -> str:
        msgs = [
            {"role": "system", "content": "Summarize the following text in 1-2 sentences for a business knowledge base. Be concise."},
            {"role": "user", "content": text[:2000]},
        ]
        return await self.chat_complete(msgs)

    # ──────────────────────────────────────────────
    #  AUTO MEETING SUMMARY
    # ──────────────────────────────────────────────
    async def generate_meeting_summary(self, messages: List[dict], channel_name: str) -> Optional[str]:
        """
        Given a list of {sender_name, content} dicts from a channel,
        produce a structured meeting summary.
        """
        if not messages or len(messages) < 3:
            return None

        conversation = "\n".join(
            f"{m['sender_name']}: {m['content']}"
            for m in messages[-60:]   # last 60 messages max
        )
        prompt_msgs = [
            {
                "role": "system",
                "content": (
                    "You are a professional meeting summarizer. "
                    "Analyse this business conversation and produce a concise summary with these sections:\n"
                    "**Key Topics Discussed** – bullet points\n"
                    "**Decisions Made** – bullet points (write 'None' if absent)\n"
                    "**Action Items** – bullet points with owner names where mentioned (write 'None' if absent)\n"
                    "**Next Steps** – bullet points (write 'None' if absent)\n"
                    "Keep it professional and under 300 words."
                ),
            },
            {"role": "user", "content": f"Channel: #{channel_name}\n\nConversation:\n{conversation}"},
        ]
        result = await self.chat_complete(prompt_msgs)
        return result if result and len(result) > 40 else None

    # ──────────────────────────────────────────────
    #  SMART ONBOARDING ASSISTANT
    # ──────────────────────────────────────────────
    async def onboarding_chat(
        self,
        user_message: str,
        history: List[dict],
        employee_name: str,
        department: str,
        db: AsyncSession,
    ) -> AsyncGenerator[str, None]:

        short_or_greeting = (
            len(user_message.strip()) < 15
            or user_message.strip().lower().rstrip("!.,") in GREETING_TRIGGERS
        )

        query = (
            f"{department} department company values culture policies procedures leave working hours tools"
            if (short_or_greeting or len(history) == 0)
            else user_message
        )

        context_chunks = await self.retrieve_context(query, db, user_role="staff", max_chunks=6)

        system_msg = (
            f"You are the BOSS Onboarding Assistant for {employee_name}, "
            f"who has already been hired and set up as a {department} department employee. "
            "Your job is to proactively guide them through the company. "
            "CRITICAL RULES YOU MUST ALWAYS FOLLOW:\n"
            "- NEVER ask the employee about themselves, their background, goals, or expectations.\n"
            "- NEVER say 'Can you tell me about yourself' or anything similar.\n"
            "- The employee's name, department, and role are already known to you.\n"
            "- If the employee reminds you that you already know them, apologize briefly and immediately provide company guidance.\n"
            "- Always respond with company information, policies, culture, tools, or procedures.\n\n"
            f"Employee: {employee_name} | Department: {department}\n\n"
            "Provide structured guidance on: company values and culture, policies and procedures, "
            "how departments work, tools and systems, leave policies, working hours, and contacts.\n\n"
        )

        if context_chunks:
            system_msg += "COMPANY KNOWLEDGE:\n"
            for i, c in enumerate(context_chunks, 1):
                system_msg += f"[{i}] {c['content']}\n\n"
        else:
            system_msg += (
                "NOTE: No company knowledge is currently in the knowledge base. "
                "Give general best-practice onboarding guidance and remind the employee "
                "to check with their manager for company-specific details.\n\n"
            )

        messages = [{"role": "system", "content": system_msg}]
        for h in history[-8:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_message})

        async for chunk in self.chat_stream(messages):
            yield chunk
    # ──────────────────────────────────────────────
    #  AI RISK DETECTION
    # ──────────────────────────────────────────────
    async def detect_risks_from_text(self, text: str, source_label: str) -> List[dict]:
        """
        Scan text (document or chat) for potential business risks.
        Returns a list of risk dicts ready to insert into risk_items.
        """
        msgs = [
            {
                "role": "system",
                "content": (
                    "You are a business risk analyst. "
                    "Scan the following text and identify potential business risks. "
                    "For each risk found, return a JSON array of objects with fields:\n"
                    "  title (string), description (string), category (one of: Operational/Financial/Legal/Technology/HR/Strategic), "
                    "  likelihood (1-5), impact (1-5), mitigation_plan (string)\n"
                    "Only identify REAL risks, not hypotheticals. "
                    "Return ONLY valid JSON array. If no risks found, return []."
                ),
            },
            {"role": "user", "content": f"Source: {source_label}\n\nText:\n{text[:3000]}"},
        ]
        result = await self.chat_complete(msgs)
        try:
            clean = result.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            if isinstance(data, list):
                # Validate and clamp values
                valid = []
                for r in data[:5]:
                    if isinstance(r, dict) and r.get("title"):
                        r["likelihood"] = max(1, min(5, int(r.get("likelihood", 3))))
                        r["impact"] = max(1, min(5, int(r.get("impact", 3))))
                        r["risk_score"] = float(r["likelihood"] * r["impact"])
                        valid.append(r)
                return valid
        except Exception as e:
            logger.error(f"Risk detection parse error: {e}")
        return []

    # ──────────────────────────────────────────────
    #  EMBED AND STORE KNOWLEDGE CHUNK
    # ──────────────────────────────────────────────
    async def embed_and_store_chunk(self, chunk_content: str) -> Optional[str]:
        """Return JSON-encoded embedding string for storage in the DB."""
        vec = self.embed(chunk_content)
        if vec:
            return json.dumps(vec)
        return None


ai_service = AIService()