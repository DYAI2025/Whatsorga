"""Context-aware Termin Extractor — uses EverMemOS memory and feedback history
to improve appointment extraction with pronoun resolution and learning.

Wraps termin_extractor.py and enriches LLM prompts with:
1. Recalled context from EverMemOS (persons, facts, events)
2. Recent feedback examples (rejected/edited termine for learning)
"""

import logging
from datetime import datetime

from sqlalchemy import select, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.evermemos_client import recall_for_termin
from app.analysis.termin_extractor import extract_termine
from app.storage.database import TerminFeedback, Termin

logger = logging.getLogger(__name__)


async def _get_recent_feedback(session: AsyncSession, limit: int = 10) -> str:
    """Load recent rejected/edited feedback as learning examples for the LLM prompt."""
    try:
        result = await session.execute(
            select(TerminFeedback, Termin.title, Termin.category, Termin.relevance)
            .join(Termin, TerminFeedback.termin_id == Termin.id)
            .where(or_(
                TerminFeedback.action == "rejected",
                TerminFeedback.action == "edited",
            ))
            .order_by(desc(TerminFeedback.created_at))
            .limit(limit)
        )
        rows = result.all()

        if not rows:
            return ""

        lines = []
        for feedback, title, category, relevance in rows:
            if feedback.action == "rejected":
                reason = feedback.reason or "kein Grund angegeben"
                lines.append(f'- "{title}" ({category}/{relevance}) wurde ABGELEHNT: {reason}')
            elif feedback.action == "edited":
                correction = feedback.correction or {}
                changes = ", ".join(f"{k}: {v}" for k, v in correction.items())
                lines.append(f'- "{title}" wurde KORRIGIERT: {changes}')

        return "\n".join(lines)

    except Exception as e:
        logger.debug(f"Failed to load feedback examples: {e}")
        return ""


async def extract_termine_with_context(
    text: str,
    sender: str,
    timestamp: datetime,
    chat_id: str,
    chat_name: str = "",
    session: AsyncSession | None = None,
) -> list:
    """Extract appointments using EverMemOS context and feedback learning.

    Flow:
    1. Recall relevant context from EverMemOS (persons, facts, events)
    2. Load recent feedback examples for learning
    3. Pass both to the LLM extractor for enriched extraction
    4. Fall back to raw extraction if context unavailable
    """
    # Build memory context string
    memory_context = ""
    try:
        memory_ctx = await recall_for_termin(text, chat_id, sender)
        if memory_ctx.has_context:
            memory_context = memory_ctx.as_prompt_block()
            logger.info(
                f"Termin extraction with {len(memory_ctx.raw_memories)} memory items "
                f"for: '{text[:60]}...'"
            )
    except Exception as e:
        logger.debug(f"EverMemOS recall for termin (non-fatal): {e}")

    # Build feedback examples string
    feedback_examples = ""
    if session:
        feedback_examples = await _get_recent_feedback(session)

    # Use the enriched extractor with context + feedback
    return await extract_termine(
        text=text,
        sender=sender,
        timestamp=timestamp,
        feedback_examples=feedback_examples,
        memory_context=memory_context,
    )
