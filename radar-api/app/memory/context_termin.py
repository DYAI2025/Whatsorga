"""Context-aware Termin Extractor — uses conversation history, existing termine,
EverMemOS memory, and feedback history to improve appointment extraction.

Enriches LLM prompts with:
1. Surrounding messages (conversation context for multi-message understanding)
2. Existing termine from DB (duplicate detection and update awareness)
3. Recalled context from EverMemOS (persons, facts, events)
4. Recent feedback examples (rejected/edited termine for learning)
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, desc, or_, and_, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.evermemos_client import recall_for_termin
from app.analysis.termin_extractor import extract_termine
from app.storage.database import TerminFeedback, Termin, Message

logger = logging.getLogger(__name__)


async def _get_conversation_context(
    session: AsyncSession,
    chat_id: str,
    timestamp: datetime,
    limit: int = 10,
) -> str:
    """Load surrounding messages for conversation context.

    Returns the 10 messages before the current one in the same chat,
    so the LLM can understand multi-message conversations and infer
    dates from context (e.g. Kontrabass pickup is on the same day as school).
    """
    try:
        result = await session.execute(
            select(Message.sender, Message.text, Message.timestamp)
            .where(
                and_(
                    Message.chat_id == chat_id,
                    Message.timestamp < timestamp,
                    Message.text.isnot(None),
                )
            )
            .order_by(desc(Message.timestamp))
            .limit(limit)
        )
        rows = result.all()

        if not rows:
            return ""

        # Reverse to chronological order
        rows = list(reversed(rows))

        lines = []
        for sender, msg_text, ts in rows:
            time_str = ts.strftime("%H:%M") if ts else ""
            # Truncate long messages
            short_text = msg_text[:300] if msg_text else ""
            lines.append(f"[{time_str}] {sender}: {short_text}")

        return "\n".join(lines)

    except Exception as e:
        logger.debug(f"Failed to load conversation context: {e}")
        return ""


async def _get_existing_termine(
    session: AsyncSession,
    chat_id: str,
    window_days: int = 60,
) -> str:
    """Load existing termine from DB to prevent duplicates.

    Returns a formatted string of recent termine so the LLM knows
    what has already been extracted and can skip duplicates.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=7)
        future_cutoff = datetime.utcnow() + timedelta(days=window_days)

        result = await session.execute(
            select(Termin)
            .join(Message, Termin.message_id == Message.id)
            .where(
                and_(
                    Message.chat_id == chat_id,
                    Termin.datetime_ >= cutoff,
                    Termin.datetime_ <= future_cutoff,
                    Termin.status != "rejected",
                )
            )
            .order_by(Termin.datetime_)
            .limit(30)
        )
        termine = result.scalars().all()

        if not termine:
            return ""

        lines = []
        for t in termine:
            dt_str = t.datetime_.strftime("%Y-%m-%d %H:%M") if t.datetime_ else "?"
            if t.all_day:
                dt_str = t.datetime_.strftime("%Y-%m-%d") + " (ganztägig)"
            lines.append(
                f"- {t.title} | {dt_str} | {t.category} | {t.relevance} | conf={t.confidence}"
            )

        return "\n".join(lines)

    except Exception as e:
        logger.debug(f"Failed to load existing termine: {e}")
        return ""


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


async def _is_duplicate(
    session: AsyncSession,
    title: str,
    dt: datetime,
    chat_id: str,
) -> bool:
    """Check if a similar termin already exists in DB (same title pattern + same day)."""
    try:
        day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        result = await session.execute(
            select(Termin)
            .join(Message, Termin.message_id == Message.id)
            .where(
                and_(
                    Message.chat_id == chat_id,
                    Termin.datetime_ >= day_start,
                    Termin.datetime_ < day_end,
                    Termin.status != "rejected",
                )
            )
        )
        existing = result.scalars().all()

        if not existing:
            return False

        # Simple title similarity: check if core words overlap
        title_words = set(title.lower().split())
        for t in existing:
            existing_words = set(t.title.lower().split())
            overlap = title_words & existing_words
            # If >50% of words match, consider it a duplicate
            if len(overlap) >= max(1, len(title_words) * 0.5):
                logger.info(f"Duplicate detected: '{title}' matches existing '{t.title}' on {dt.date()}")
                return True

        return False

    except Exception as e:
        logger.debug(f"Duplicate check failed: {e}")
        return False


async def extract_termine_with_context(
    text: str,
    sender: str,
    timestamp: datetime,
    chat_id: str,
    chat_name: str = "",
    session: AsyncSession | None = None,
) -> list:
    """Extract appointments using full context: conversation, existing termine, memory, feedback.

    Flow:
    1. Load surrounding messages for conversation context
    2. Load existing termine for duplicate awareness
    3. Recall relevant context from EverMemOS
    4. Load recent feedback examples for learning
    5. Pass everything to the LLM extractor
    6. Post-filter: check for duplicates before returning
    """
    # 1. Conversation context (surrounding messages)
    conversation_context = ""
    if session:
        conversation_context = await _get_conversation_context(session, chat_id, timestamp)

    # 2. Existing termine
    existing_termine = ""
    if session:
        existing_termine = await _get_existing_termine(session, chat_id)

    # 3. Memory context from EverMemOS
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

    # 4. Feedback examples
    feedback_examples = ""
    if session:
        feedback_examples = await _get_recent_feedback(session)

    # 5. LLM extraction with full context
    results = await extract_termine(
        text=text,
        sender=sender,
        timestamp=timestamp,
        feedback_examples=feedback_examples,
        memory_context=memory_context,
        conversation_context=conversation_context,
        existing_termine=existing_termine,
    )

    # 6. Post-filter: remove duplicates that the LLM missed
    if session and results:
        filtered = []
        for t in results:
            try:
                termin_dt = datetime.fromisoformat(t.datetime_str) if t.datetime_str else None
                if termin_dt and await _is_duplicate(session, t.title, termin_dt, chat_id):
                    logger.info(f"Post-filter removed duplicate: '{t.title}' @ {t.datetime_str}")
                    continue
                filtered.append(t)
            except Exception:
                filtered.append(t)
        return filtered

    return results
