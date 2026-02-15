"""EverMemOS Client — async HTTP bridge to the EverMemOS memory service.

Provides memorize() and recall() as the two core operations:
  - memorize(): Every incoming WhatsApp message → EverMemOS MemCells
  - recall():   Before any analysis step, pull relevant context from memory

The client is resilient: if EverMemOS is down, Whatsorga continues without context.
"""

import logging
import httpx
from datetime import datetime
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

# ─── Configuration ───────────────────────────────────────────────────────────

EVERMEMOS_BASE_URL = getattr(settings, "evermemos_url", "http://evermemos:8001")
EVERMEMOS_TIMEOUT = 15.0  # seconds


# ─── Data structures ────────────────────────────────────────────────────────

@dataclass
class MemoryContext:
    """Recalled context from EverMemOS for a given query."""
    episodes: list[dict] = field(default_factory=list)
    profiles: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    raw_memories: list[str] = field(default_factory=list)

    @property
    def has_context(self) -> bool:
        return bool(self.episodes or self.profiles or self.facts or self.raw_memories)

    def as_prompt_block(self) -> str:
        """Format recalled memories as a context block for LLM prompts."""
        if not self.has_context:
            return ""

        parts = ["<kontext_gedächtnis>"]

        if self.profiles:
            parts.append("## Personenprofile")
            for p in self.profiles[:5]:
                content = p.get("content", p.get("text", str(p)))
                parts.append(f"- {content}")

        if self.episodes:
            parts.append("## Relevante Episoden")
            for e in self.episodes[:10]:
                content = e.get("content", e.get("text", str(e)))
                ts = e.get("timestamp", "")
                parts.append(f"- [{ts}] {content}")

        if self.facts:
            parts.append("## Bekannte Fakten")
            for f in self.facts[:10]:
                content = f.get("content", f.get("text", str(f)))
                parts.append(f"- {content}")

        if self.raw_memories:
            parts.append("## Weitere Erinnerungen")
            for m in self.raw_memories[:5]:
                parts.append(f"- {m}")

        parts.append("</kontext_gedächtnis>")
        return "\n".join(parts)


# ─── HTTP Client (connection-pooled, lazy-init) ─────────────────────────────

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=EVERMEMOS_BASE_URL,
            timeout=EVERMEMOS_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
    return _client


async def close():
    """Shutdown hook — call during app shutdown."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


# ─── Core Operations ────────────────────────────────────────────────────────

async def memorize(
    chat_id: str,
    chat_name: str,
    sender: str,
    text: str,
    timestamp: datetime,
    message_id: str = "",
    scene: str = "assistant",
) -> dict | None:
    """Store a message in EverMemOS.

    Maps Whatsorga's message model to EverMemOS's /api/v3/agentic/memorize.
    Non-blocking: returns None on failure so the pipeline continues.
    """
    if not text or not text.strip():
        return None

    payload = {
        "message_id": message_id or f"{chat_id}_{timestamp.isoformat()}",
        "create_time": timestamp.isoformat(),
        "sender": sender,
        "sender_name": sender,
        "content": text,
        "group_id": chat_id,
        "group_name": chat_name,
        "scene": scene,
    }

    try:
        client = _get_client()
        resp = await client.post("/api/v3/agentic/memorize", json=payload)
        resp.raise_for_status()
        result = resp.json()
        saved = result.get("result", {}).get("count", 0)
        logger.info(f"EverMemOS: memorized message from {sender} in {chat_name} ({saved} memories)")
        return result
    except httpx.ConnectError:
        logger.debug("EverMemOS not reachable — continuing without memory storage")
        return None
    except Exception as e:
        logger.warning(f"EverMemOS memorize error (non-fatal): {e}")
        return None


async def recall(
    query: str,
    chat_id: str | None = None,
    user_id: str | None = None,
    mode: str = "rrf",
    top_k: int = 10,
) -> MemoryContext:
    """Recall relevant context from EverMemOS.

    Uses lightweight retrieval (Embedding + BM25 + RRF fusion) for speed.
    Falls back to empty context if EverMemOS is unavailable.
    """
    ctx = MemoryContext()

    if not query or not query.strip():
        return ctx

    # Step 1: Episode retrieval (conversation history, events)
    episodes = await _retrieve(
        query=query,
        group_id=chat_id,
        user_id=user_id,
        data_source="episode",
        mode=mode,
        top_k=top_k,
    )
    ctx.episodes = episodes

    # Step 2: Profile retrieval (person knowledge, relationships)
    profiles = await _retrieve(
        query=query,
        group_id=chat_id,
        user_id=user_id,
        data_source="profile",
        mode=mode,
        top_k=5,
    )
    ctx.profiles = profiles

    # Step 3: Semantic memory (facts, dates, preferences)
    facts = await _retrieve(
        query=query,
        group_id=chat_id,
        user_id=user_id,
        data_source="semantic_memory",
        mode=mode,
        top_k=5,
    )
    ctx.facts = facts

    # Collect raw text for easy consumption
    for source in [episodes, profiles, facts]:
        for item in source:
            text = item.get("content", item.get("text", ""))
            if text and text not in ctx.raw_memories:
                ctx.raw_memories.append(text)

    if ctx.has_context:
        logger.info(
            f"EverMemOS: recalled {len(ctx.episodes)} episodes, "
            f"{len(ctx.profiles)} profiles, {len(ctx.facts)} facts "
            f"for query '{query[:50]}...'"
        )

    return ctx


async def recall_for_termin(
    text: str,
    chat_id: str,
    sender: str,
) -> MemoryContext:
    """Specialized recall for appointment extraction.

    Queries EverMemOS with the message text + person-specific context
    to resolve pronouns, dates, and implicit references.
    """
    # Build a richer query that helps EverMemOS find relevant context
    enriched_query = f"Termine Geburtstage Verabredungen Ereignisse: {text}"

    ctx = await recall(
        query=enriched_query,
        chat_id=chat_id,
        user_id=sender,
        top_k=15,
    )

    # Also try person-specific queries if pronouns detected
    pronoun_markers = ["ihr", "sein", "ihm", "ihrer", "seinem", "deren", "dessen"]
    has_pronouns = any(p in text.lower().split() for p in pronoun_markers)

    if has_pronouns:
        person_ctx = await recall(
            query=f"Person Familie Beziehung Geburtstag {sender}",
            chat_id=chat_id,
            user_id=sender,
            top_k=5,
        )
        ctx.profiles.extend(person_ctx.profiles)
        ctx.facts.extend(person_ctx.facts)

    return ctx


# ─── Internal helpers ────────────────────────────────────────────────────────

async def _retrieve(
    query: str,
    group_id: str | None = None,
    user_id: str | None = None,
    data_source: str = "episode",
    mode: str = "rrf",
    top_k: int = 10,
) -> list[dict]:
    """Low-level retrieval call to EverMemOS."""

    payload = {
        "query": query,
        "data_source": data_source,
        "retrieval_mode": mode,
        "top_k": top_k,
        "memory_scope": "all",
    }

    if group_id:
        payload["group_id"] = group_id
    if user_id:
        payload["user_id"] = user_id

    # Profile queries need both IDs
    if data_source == "profile":
        if not group_id or not user_id:
            payload["memory_scope"] = "group" if group_id else "personal"

    try:
        client = _get_client()
        resp = await client.post("/api/v3/agentic/retrieve_lightweight", json=payload)
        resp.raise_for_status()
        result = resp.json()
        memories = result.get("result", {}).get("memories", [])
        return memories if isinstance(memories, list) else []
    except httpx.ConnectError:
        return []
    except Exception as e:
        logger.debug(f"EverMemOS retrieve ({data_source}) error: {e}")
        return []


# ─── Health check ────────────────────────────────────────────────────────────

async def health_check() -> dict:
    """Check if EverMemOS is reachable and healthy."""
    try:
        client = _get_client()
        resp = await client.get("/health", timeout=5.0)
        return {"status": "ok", "evermemos": "connected", "url": EVERMEMOS_BASE_URL}
    except Exception as e:
        return {"status": "degraded", "evermemos": "unreachable", "error": str(e)}
