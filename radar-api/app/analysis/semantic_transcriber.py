"""Semantic Transcriber — enriches audio transcripts with conversation context.

Uses recent chat messages (SQL) + similar messages (ChromaDB) as context,
then asks Groq LLM (primary) or Gemini (fallback) for semantic enrichment.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.storage.database import Message
from app.storage.rag_store import rag_store

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_LLM_MODEL = "llama-3.3-70b-versatile"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

SYSTEM_PROMPT = """Du bist ein semantischer Kontext-Assistent für WhatsApp-Sprachnachrichten.
Du bekommst eine rohe Transkription und den Chatverlauf als Kontext.
Erstelle eine kontextreiche Version der Sprachnachricht.
Antworte NUR mit JSON: {"enriched": "...", "summary": "...", "topics": ["..."], "confidence": 0.0-1.0}"""


@dataclass
class EnrichedTranscript:
    raw: str
    enriched: str
    summary: str
    topics: list[str] = field(default_factory=list)
    confidence: float = 0.0
    provider: str = "none"


async def enrich_transcript(
    session: AsyncSession,
    raw_transcript: str,
    chat_id: str,
    sender: str,
    timestamp: datetime,
) -> EnrichedTranscript:
    """Orchestrator: fetch context, call Groq or Gemini, return enriched transcript."""
    if not raw_transcript or len(raw_transcript.strip()) < 3:
        return EnrichedTranscript(
            raw=raw_transcript, enriched=raw_transcript,
            summary=raw_transcript, confidence=0.0,
        )

    # Gather context
    recent = await _fetch_recent_messages(session, chat_id, timestamp)
    similar = await _fetch_similar_messages(raw_transcript)
    user_prompt = _build_user_prompt(recent, similar, raw_transcript, sender, timestamp)

    # Try Groq first
    result = await _call_groq_llm(user_prompt)
    if result:
        return _make_enriched(raw_transcript, result, "groq")

    # Fallback to Gemini
    result = await _call_gemini(user_prompt)
    if result:
        return _make_enriched(raw_transcript, result, "gemini")

    # All failed: return raw
    logger.info("All enrichment providers failed, using raw transcript")
    return EnrichedTranscript(
        raw=raw_transcript, enriched=raw_transcript,
        summary=raw_transcript, confidence=0.0, provider="none",
    )


def _make_enriched(raw: str, result: dict, provider: str) -> EnrichedTranscript:
    return EnrichedTranscript(
        raw=raw,
        enriched=result.get("enriched", raw),
        summary=result.get("summary", raw),
        topics=result.get("topics", []),
        confidence=float(result.get("confidence", 0.5)),
        provider=provider,
    )


async def _fetch_recent_messages(
    session: AsyncSession,
    chat_id: str,
    before_ts: datetime,
    limit: int = 10,
) -> list[dict]:
    """Get the last N messages in the same chat before the given timestamp."""
    try:
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id, Message.timestamp < before_ts)
            .order_by(desc(Message.timestamp))
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

        messages = []
        for row in reversed(rows):
            messages.append({
                "sender": row.sender,
                "text": row.text or "",
                "timestamp": row.timestamp.strftime("%H:%M") if row.timestamp else "",
            })
        return messages
    except Exception as e:
        logger.warning(f"Failed to fetch recent messages: {e}")
        return []


async def _fetch_similar_messages(raw_transcript: str, n: int = 5) -> list[dict]:
    """Find semantically similar messages via ChromaDB."""
    try:
        results = await rag_store.query_similar(raw_transcript, n_results=n)
        return results
    except Exception as e:
        logger.warning(f"ChromaDB similarity search failed: {e}")
        return []


def _build_user_prompt(
    recent: list[dict],
    similar: list[dict],
    raw_transcript: str,
    sender: str,
    timestamp: datetime,
) -> str:
    """Format the context window for the LLM prompt."""
    lines = []

    if recent:
        lines.append("--- Letzte Nachrichten im Chat ---")
        for msg in recent:
            lines.append(f"[{msg['timestamp']}] {msg['sender']}: {msg['text']}")

    if similar:
        lines.append("")
        lines.append("--- Ähnliche Nachrichten (Kontext) ---")
        for item in similar[:5]:
            meta = item.get("metadata", {})
            sender_name = meta.get("sender", "?")
            text = item.get("text", "")
            lines.append(f"{sender_name}: {text}")

    if not lines:
        lines.append("(Kein vorheriger Kontext verfügbar)")

    formatted = "\n".join(lines)
    ts_str = timestamp.strftime("%H:%M, %d.%m.%Y")

    return f"""CHATVERLAUF:
{formatted}

SPRACHNACHRICHT von {sender} ({ts_str}):
"{raw_transcript}"
"""


def _parse_json_response(text: str) -> dict | None:
    """Extract JSON object from LLM response text."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


async def _call_groq_llm(user_prompt: str) -> dict | None:
    """Send prompt to Groq chat completions API."""
    if not settings.groq_api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json={
                    "model": GROQ_LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                    "response_format": {"type": "json_object"},
                },
            )

            if resp.status_code != 200:
                logger.warning(f"Groq LLM error: {resp.status_code} — {resp.text[:200]}")
                return None

            content = resp.json()["choices"][0]["message"]["content"].strip()
            result = _parse_json_response(content)
            if not result:
                logger.warning("Groq LLM returned no valid JSON")
            return result

    except Exception as e:
        logger.warning(f"Groq LLM error: {e}")
        return None


async def _call_gemini(user_prompt: str) -> dict | None:
    """Send prompt to Gemini API (fallback)."""
    if not settings.gemini_api_key:
        return None

    try:
        combined = f"{SYSTEM_PROMPT}\n\n{user_prompt}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{GEMINI_URL}?key={settings.gemini_api_key}",
                json={
                    "contents": [{"parts": [{"text": combined}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 1024,
                        "responseMimeType": "application/json",
                    },
                },
            )

            if resp.status_code != 200:
                logger.warning(f"Gemini error: {resp.status_code} — {resp.text[:200]}")
                return None

            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            # Gemini 2.5 may return thinking parts (thought=true) + response
            content = ""
            for part in parts:
                if "text" in part and not part.get("thought", False):
                    content = part["text"].strip()
            if not content:
                for part in reversed(parts):
                    if "text" in part:
                        content = part["text"].strip()
                        break
            result = _parse_json_response(content)
            if not result:
                logger.warning("Gemini returned no valid JSON")
            return result

    except Exception as e:
        logger.warning(f"Gemini error: {e}")
        return None
