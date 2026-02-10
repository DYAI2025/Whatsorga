"""Semantic Chat Weaver — thread detection and drift computation.

Cherry-picked from Super_semantic_whisper SemanticChatWeaver.
Adapted for Beziehungs-Radar: uses ChromaDB RAG for similarity,
PostgreSQL threads table for persistence.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.database import Thread, Analysis, Message
from app.storage.rag_store import rag_store

logger = logging.getLogger(__name__)

# Thread detection thresholds
SIMILARITY_THRESHOLD = 0.3  # cosine distance (lower = more similar)
MIN_THREAD_MESSAGES = 3
THREAD_TIMEOUT_HOURS = 72  # threads go dormant after 3 days


async def process_message_context(
    session: AsyncSession,
    message_id: UUID,
    chat_id: str,
    text: str,
    sender: str,
    timestamp: datetime,
    sentiment_score: float,
    markers: dict,
):
    """Process a message in context: embed in RAG, update threads."""
    if not text:
        return

    # 1. Store in RAG
    metadata = {
        "chat_id": chat_id,
        "sender": sender,
        "timestamp": timestamp.isoformat(),
        "sentiment": sentiment_score,
        "dominant_marker": markers.get("dominant", ""),
    }
    await rag_store.add_message(message_id, text, metadata)

    # 2. Query similar messages for context
    similar = await rag_store.query_similar(text, n_results=20)

    # 3. Try to attach to existing thread or create new one
    await _update_threads(
        session, message_id, chat_id, text, sender,
        timestamp, sentiment_score, markers, similar,
    )


async def _update_threads(
    session: AsyncSession,
    message_id: UUID,
    chat_id: str,
    text: str,
    sender: str,
    timestamp: datetime,
    sentiment_score: float,
    markers: dict,
    similar_messages: list[dict],
):
    """Attach message to a thread or create a new one."""
    # Get active threads for this chat
    result = await session.execute(
        select(Thread).where(
            and_(Thread.chat_id == chat_id, Thread.status == "active")
        )
    )
    active_threads = list(result.scalars().all())

    best_thread = None
    best_overlap = 0

    for thread in active_threads:
        thread_msg_ids = set(thread.message_ids or [])
        similar_ids = {m["id"] for m in similar_messages if m["distance"] < SIMILARITY_THRESHOLD}

        overlap = len(thread_msg_ids & similar_ids)
        if overlap > best_overlap:
            best_overlap = overlap
            best_thread = thread

    if best_thread and best_overlap >= 1:
        # Attach to existing thread
        msg_ids = list(best_thread.message_ids or [])
        msg_ids.append(str(message_id))
        best_thread.message_ids = msg_ids

        arc = list(best_thread.emotional_arc or [])
        arc.append(sentiment_score)
        best_thread.emotional_arc = arc

        best_thread.updated_at = datetime.now(timezone.utc)

        # Check for dormancy
        if len(msg_ids) >= MIN_THREAD_MESSAGES:
            _detect_tension(best_thread)

    else:
        # Create new thread
        dominant = markers.get("dominant", "general")
        new_thread = Thread(
            chat_id=chat_id,
            theme=dominant,
            message_ids=[str(message_id)],
            emotional_arc=[sentiment_score],
            status="active",
        )
        session.add(new_thread)

    # Mark old threads as dormant
    cutoff = datetime.now(timezone.utc) - timedelta(hours=THREAD_TIMEOUT_HOURS)
    for thread in active_threads:
        if thread.updated_at and thread.updated_at < cutoff:
            thread.status = "ruhend"


def _detect_tension(thread: Thread):
    """Detect tension and resolution points in emotional arc."""
    arc = thread.emotional_arc or []
    if len(arc) < 3:
        return

    # Simple tension detection: consecutive drops
    tension_count = 0
    for i in range(1, len(arc)):
        if arc[i] < arc[i - 1] - 0.1:
            tension_count += 1

    # If recent sentiment is recovering after a dip, mark as resolving
    if len(arc) >= 3 and arc[-1] > arc[-2] and arc[-2] < -0.2:
        thread.status = "active"  # resolving tension
