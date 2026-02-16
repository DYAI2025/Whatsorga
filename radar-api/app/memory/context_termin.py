"""Context-aware Termin Extractor — uses EverMemOS memory to resolve pronouns,
dates, and implicit references in appointment extraction.

This wraps the existing termin_extractor.py and enriches LLM prompts with
recalled context from EverMemOS before extracting appointments.

Example:
    Message: "Kannst du an ihrem Geburtstag Süßigkeiten-Tüten mitbringen?"
    Without context → Termin: unknown date, unknown person
    With context   → Termin: 21.02. (Romys Feier), 8 Süßigkeiten-Tüten

This is the module that solves the "Marike/Romy-Problem".
"""

import logging
from datetime import datetime

from app.memory.evermemos_client import recall_for_termin, MemoryContext
from app.analysis.termin_extractor import extract_termine as _extract_raw

logger = logging.getLogger(__name__)


# ─── Enhanced LLM prompt template ────────────────────────────────────────────

CONTEXT_TERMIN_PROMPT = """Du bist ein Termin-Extraktions-System für deutschsprachige WhatsApp-Nachrichten.

{memory_context}

AKTUELLE NACHRICHT:
Sender: {sender}
Zeitpunkt: {timestamp}
Text: "{text}"

AUFGABE:
1. Löse alle Pronomen auf ("ihrem" → wer genau? Nutze den Kontext oben)
2. Bestimme das exakte Datum (unterscheide z.B. Geburtstag vs. Geburtstagsfeier)
3. Extrahiere alle Termine, Aufgaben und Erinnerungen
4. Ordne Teilnehmer und Mengenangaben aus dem Kontext zu

Antworte als JSON-Array:
[{{
  "title": "Beschreibung der Aufgabe/des Termins",
  "datetime": "YYYY-MM-DDTHH:MM:SS",
  "participants": ["Name1", "Name2"],
  "confidence": 0.0-1.0,
  "resolved_references": {{
    "pronouns": {{"ihrem": "Romy"}},
    "implicit_dates": {{"Geburtstag": "2026-02-18", "Feier": "2026-02-21"}}
  }},
  "context_used": "Kurze Erklärung welcher Kontext half"
}}]

Wenn keine Termine erkannt werden: []
"""


async def extract_termine_with_context(
    text: str,
    sender: str,
    timestamp: datetime,
    chat_id: str,
    chat_name: str = "",
) -> list:
    """Extract appointments using EverMemOS context for disambiguation.

    Flow:
    1. Recall relevant context from EverMemOS (persons, facts, events)
    2. If context found → use enriched LLM prompt for extraction
    3. If no context   → fall back to raw extraction (existing behavior)

    Returns the same TerminResult objects as the original extractor.
    """

    # Step 1: Try to recall context from EverMemOS
    memory_ctx = await recall_for_termin(text, chat_id, sender)

    if memory_ctx.has_context:
        logger.info(
            f"Termin extraction with {len(memory_ctx.raw_memories)} memory items "
            f"for: '{text[:60]}...'"
        )
        # Step 2: Use context-enriched extraction
        return await _extract_with_context(text, sender, timestamp, memory_ctx)
    else:
        # Step 3: Fallback to existing extraction (no context available)
        logger.debug("No EverMemOS context available, using raw extraction")
        return await _extract_raw(text, sender, timestamp)


async def _extract_with_context(
    text: str,
    sender: str,
    timestamp: datetime,
    ctx: MemoryContext,
) -> list:
    """Run LLM termin extraction with injected memory context.

    Uses Groq/Gemini (same as existing extractor) but with enriched prompts.
    """
    # For now, inject context into the existing extraction pipeline
    # by prepending context to the text that gets analyzed.
    #
    # The enriched text gives the LLM everything it needs:
    context_block = ctx.as_prompt_block()
    enriched_text = f"{context_block}\n\nNachricht: {text}"

    # Use the existing extractor with the enriched text
    # This ensures backward compatibility while adding context
    try:
        results = await _extract_raw(enriched_text, sender, timestamp)

        # Log what context helped with
        if results:
            logger.info(
                f"Context-enriched extraction found {len(results)} Termine "
                f"(context had {len(ctx.profiles)} profiles, {len(ctx.facts)} facts)"
            )

        return results

    except Exception as e:
        logger.warning(f"Context-enriched extraction failed, falling back: {e}")
        return await _extract_raw(text, sender, timestamp)


async def enrich_text_with_context(
    text: str,
    chat_id: str,
    sender: str,
) -> tuple[str, MemoryContext]:
    """Enrich any text with EverMemOS context.

    Used by the semantic_transcriber and other analysis modules
    to get context for any message, not just appointments.

    Returns (enriched_text, context) tuple.
    """
    from app.memory.evermemos_client import recall

    ctx = await recall(
        query=text,
        chat_id=chat_id,
        user_id=sender,
        top_k=10,
    )

    if ctx.has_context:
        context_block = ctx.as_prompt_block()
        enriched = f"{context_block}\n\n{text}"
        return enriched, ctx

    return text, ctx
