"""Dashboard API endpoints — serves data for the frontend views."""

import logging
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.storage.database import get_session, Message, Analysis, DriftSnapshot, Thread, Termin, TerminFeedback, CaptureStats
from app.storage.rag_store import rag_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def verify_api_key(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[7:]
    if token != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


@router.get("/drift/{chat_id}")
async def get_drift(
    chat_id: str,
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Get sentiment drift data for chart rendering."""
    since = datetime.utcnow() - timedelta(days=days)

    # Get daily aggregated sentiment from analysis table
    result = await session.execute(
        select(
            func.date(Message.timestamp).label("date"),
            func.avg(Analysis.sentiment_score).label("avg_sentiment"),
            func.count(Message.id).label("message_count"),
        )
        .join(Analysis, Analysis.message_id == Message.id)
        .where(and_(Message.chat_id == chat_id, Message.timestamp >= since))
        .group_by(func.date(Message.timestamp))
        .order_by(func.date(Message.timestamp))
    )
    rows = result.all()

    return {
        "chat_id": chat_id,
        "days": days,
        "data": [
            {
                "date": str(r.date),
                "avg_sentiment": round(r.avg_sentiment, 3) if r.avg_sentiment else 0,
                "message_count": r.message_count,
            }
            for r in rows
        ],
    }


@router.get("/markers/{chat_id}")
async def get_markers(
    chat_id: str,
    days: int = Query(default=7, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Get marker distribution for heatmap rendering."""
    since = datetime.utcnow() - timedelta(days=days)

    result = await session.execute(
        select(
            func.date(Message.timestamp).label("date"),
            Analysis.markers,
        )
        .join(Analysis, Analysis.message_id == Message.id)
        .where(and_(Message.chat_id == chat_id, Message.timestamp >= since))
        .order_by(func.date(Message.timestamp))
    )
    rows = result.all()

    # Aggregate markers per day
    daily_markers: dict[str, dict[str, int]] = {}
    for r in rows:
        date_str = str(r.date)
        if date_str not in daily_markers:
            daily_markers[date_str] = {}
        if r.markers:
            for marker, count in r.markers.items():
                daily_markers[date_str][marker] = daily_markers[date_str].get(marker, 0) + count

    return {
        "chat_id": chat_id,
        "days": days,
        "data": [
            {"date": date, "markers": markers}
            for date, markers in sorted(daily_markers.items())
        ],
    }


@router.get("/threads/{chat_id}")
async def get_threads(
    chat_id: str,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Get semantic threads for a chat."""
    result = await session.execute(
        select(Thread)
        .where(Thread.chat_id == chat_id)
        .order_by(desc(Thread.updated_at))
        .limit(50)
    )
    threads = result.scalars().all()

    return {
        "chat_id": chat_id,
        "threads": [
            {
                "id": str(t.id),
                "theme": t.theme,
                "status": t.status,
                "message_count": len(t.message_ids) if t.message_ids else 0,
                "emotional_arc": t.emotional_arc or [],
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in threads
        ],
    }


@router.get("/termine/{chat_id}")
async def get_termine(
    chat_id: str,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Get upcoming appointments extracted from messages."""
    result = await session.execute(
        select(Termin, Message.chat_id)
        .join(Message, Termin.message_id == Message.id)
        .where(and_(Message.chat_id == chat_id, Termin.datetime_ >= datetime.utcnow()))
        .order_by(Termin.datetime_)
        .limit(20)
    )
    rows = result.all()

    return {
        "chat_id": chat_id,
        "termine": [
            {
                "id": str(t.id),
                "title": t.title,
                "datetime": t.datetime_.isoformat() if t.datetime_ else None,
                "participants": t.participants or [],
                "confidence": t.confidence,
                "caldav_synced": bool(t.caldav_uid),
                "category": t.category or "appointment",
                "relevance": t.relevance or "shared",
                "status": t.status or "auto",
            }
            for t, _ in rows
        ],
    }


class FeedbackPayload(BaseModel):
    action: str  # confirmed | rejected | edited
    correction: dict | None = None  # for "edited": {"title": "...", "datetime": "..."}
    reason: str | None = None


@router.post("/termine/{termin_id}/feedback")
async def submit_termin_feedback(
    termin_id: str,
    payload: FeedbackPayload,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Submit feedback for an extracted termin (confirm/reject/edit).

    - confirmed: Keeps the termin, updates status
    - rejected: Marks as rejected, stored for learning
    - edited: Applies corrections, stored for learning
    """
    import uuid as uuid_mod

    # Validate action
    if payload.action not in ("confirmed", "rejected", "edited"):
        raise HTTPException(status_code=400, detail="action must be: confirmed, rejected, edited")

    # Find the termin
    try:
        termin_uuid = uuid_mod.UUID(termin_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid termin ID")

    result = await session.execute(
        select(Termin).where(Termin.id == termin_uuid)
    )
    termin = result.scalar_one_or_none()
    if not termin:
        raise HTTPException(status_code=404, detail="Termin not found")

    # Store feedback
    feedback = TerminFeedback(
        termin_id=termin_uuid,
        action=payload.action,
        correction=payload.correction,
        reason=payload.reason,
    )
    session.add(feedback)

    # Update termin status
    termin.status = payload.action

    # Apply corrections if edited
    if payload.action == "edited" and payload.correction:
        if "title" in payload.correction:
            termin.title = payload.correction["title"]
        if "datetime" in payload.correction:
            try:
                termin.datetime_ = datetime.fromisoformat(payload.correction["datetime"])
            except ValueError:
                pass
        if "category" in payload.correction:
            termin.category = payload.correction["category"]
        if "relevance" in payload.correction:
            termin.relevance = payload.correction["relevance"]

    await session.commit()

    return {
        "termin_id": termin_id,
        "action": payload.action,
        "status": "ok",
    }


@router.get("/pipeline/{chat_id}")
async def get_pipeline(
    chat_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Get recent termin extractions with full processing metadata for pipeline view."""
    result = await session.execute(
        select(Termin, Message.text, Message.sender, Message.timestamp)
        .join(Message, Termin.message_id == Message.id)
        .where(Message.chat_id == chat_id)
        .order_by(desc(Termin.created_at))
        .limit(limit)
    )
    rows = result.all()

    return {
        "chat_id": chat_id,
        "pipeline": [
            {
                "id": str(t.id),
                "title": t.title,
                "datetime": t.datetime_.isoformat() if t.datetime_ else None,
                "participants": t.participants or [],
                "confidence": t.confidence,
                "category": t.category or "appointment",
                "relevance": t.relevance or "shared",
                "status": t.status or "auto",
                "reminders": t.reminder_config or [],
                "caldav_synced": bool(t.caldav_uid),
                "created_at": t.created_at.isoformat() if t.created_at else None,
                # Source message
                "source_text": (msg_text or "")[:300],
                "source_sender": msg_sender,
                "source_timestamp": msg_ts.isoformat() if msg_ts else None,
            }
            for t, msg_text, msg_sender, msg_ts in rows
        ],
    }


@router.get("/drift-markers/{chat_id}")
async def get_drift_markers(
    chat_id: str,
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Get combined sentiment + dominant markers per day for colored chart dots."""
    since = datetime.utcnow() - timedelta(days=days)

    # Get daily sentiment + markers in one query
    result = await session.execute(
        select(
            func.date(Message.timestamp).label("date"),
            func.avg(Analysis.sentiment_score).label("avg_sentiment"),
            func.count(Message.id).label("message_count"),
            Analysis.marker_categories,
        )
        .join(Analysis, Analysis.message_id == Message.id)
        .where(and_(Message.chat_id == chat_id, Message.timestamp >= since))
        .group_by(func.date(Message.timestamp), Analysis.marker_categories)
        .order_by(func.date(Message.timestamp))
    )
    rows = result.all()

    # Aggregate per day: sentiment + total marker counts
    day_data: dict[str, dict] = {}
    for r in rows:
        date_str = str(r.date)
        if date_str not in day_data:
            day_data[date_str] = {
                "date": date_str,
                "avg_sentiment": 0,
                "message_count": 0,
                "marker_totals": {},
                "_sentiment_sum": 0,
                "_sentiment_count": 0,
            }
        d = day_data[date_str]
        d["message_count"] += r.message_count
        d["_sentiment_sum"] += (r.avg_sentiment or 0) * r.message_count
        d["_sentiment_count"] += r.message_count

        # Accumulate marker counts from categories
        if r.marker_categories and isinstance(r.marker_categories, dict):
            cats = r.marker_categories.get("categories", {})
            if isinstance(cats, dict):
                for marker, score in cats.items():
                    d["marker_totals"][marker] = d["marker_totals"].get(marker, 0) + (score if isinstance(score, (int, float)) else 1)

    # Finalize
    data_points = []
    for date_str in sorted(day_data.keys()):
        d = day_data[date_str]
        avg = d["_sentiment_sum"] / d["_sentiment_count"] if d["_sentiment_count"] else 0
        # Find dominant marker
        dominant = max(d["marker_totals"], key=d["marker_totals"].get) if d["marker_totals"] else None
        data_points.append({
            "date": date_str,
            "avg_sentiment": round(avg, 3),
            "message_count": d["message_count"],
            "dominant_marker": dominant,
            "markers": d["marker_totals"],
        })

    return {
        "chat_id": chat_id,
        "days": days,
        "data": data_points,
    }


@router.get("/search")
async def search_messages(
    q: str = Query(..., min_length=2),
    chat_id: str = Query(default=""),
    _auth: None = Depends(verify_api_key),
):
    """RAG-powered semantic search across all messages."""
    results = await rag_store.query_similar(q, n_results=20)

    # Filter by chat_id if provided
    if chat_id:
        results = [r for r in results if r.get("metadata", {}).get("chat_id") == chat_id]

    return {
        "query": q,
        "results": [
            {
                "id": r["id"],
                "text": r["text"],
                "sender": r.get("metadata", {}).get("sender", ""),
                "timestamp": r.get("metadata", {}).get("timestamp", ""),
                "sentiment": r.get("metadata", {}).get("sentiment", 0),
                "distance": round(r.get("distance", 1.0), 3),
            }
            for r in results
        ],
    }


@router.get("/overview/{chat_id}")
async def get_overview(
    chat_id: str,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Dashboard overview: total messages, avg sentiment, active threads, upcoming termine."""
    # Total messages
    msg_count = await session.execute(
        select(func.count(Message.id)).where(Message.chat_id == chat_id)
    )
    total_messages = msg_count.scalar() or 0

    # Avg sentiment (last 7 days)
    since_7d = datetime.utcnow() - timedelta(days=7)
    avg_result = await session.execute(
        select(func.avg(Analysis.sentiment_score))
        .join(Message, Analysis.message_id == Message.id)
        .where(and_(Message.chat_id == chat_id, Message.timestamp >= since_7d))
    )
    avg_sentiment = avg_result.scalar()

    # Active threads
    thread_count = await session.execute(
        select(func.count(Thread.id)).where(
            and_(Thread.chat_id == chat_id, Thread.status == "active")
        )
    )
    active_threads = thread_count.scalar() or 0

    # Upcoming termine
    termin_count = await session.execute(
        select(func.count(Termin.id))
        .join(Message, Termin.message_id == Message.id)
        .where(and_(Message.chat_id == chat_id, Termin.datetime_ >= datetime.utcnow()))
    )
    upcoming_termine = termin_count.scalar() or 0

    return {
        "chat_id": chat_id,
        "total_messages": total_messages,
        "avg_sentiment_7d": round(avg_sentiment, 3) if avg_sentiment else 0,
        "active_threads": active_threads,
        "upcoming_termine": upcoming_termine,
    }


@router.get("/status")
async def get_service_status(
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Check health of all pipeline services: Whisper, Groq LLM, Gemini, ChromaDB, CalDAV, Termine."""

    async def _check(name: str, coro):
        try:
            return await coro
        except Exception as e:
            return {"name": name, "status": "error", "detail": str(e)}

    async with httpx.AsyncClient(timeout=5.0) as client:
        services = []

        # 1. Groq Whisper
        if settings.groq_api_key:
            try:
                r = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                )
                services.append({
                    "name": "Whisper (Groq)",
                    "status": "ok" if r.status_code == 200 else "error",
                    "detail": settings.groq_whisper_model,
                })
            except Exception as e:
                services.append({"name": "Whisper (Groq)", "status": "error", "detail": str(e)})
        else:
            services.append({"name": "Whisper (Groq)", "status": "off", "detail": "Kein API-Key"})

        # 2. Groq LLM
        if settings.groq_api_key:
            services.append({
                "name": "LLM (Groq)",
                "status": "ok",
                "detail": "llama-3.3-70b-versatile",
            })
        else:
            services.append({"name": "LLM (Groq)", "status": "off", "detail": "Kein API-Key"})

        # 3. Gemini
        if settings.gemini_api_key:
            try:
                r = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={settings.gemini_api_key}",
                )
                services.append({
                    "name": "LLM (Gemini)",
                    "status": "ok" if r.status_code == 200 else "error",
                    "detail": "gemini-2.5-flash (Fallback)",
                })
            except Exception as e:
                services.append({"name": "LLM (Gemini)", "status": "error", "detail": str(e)})
        else:
            services.append({"name": "LLM (Gemini)", "status": "off", "detail": "Kein API-Key"})

        # 4. ChromaDB
        try:
            r = await client.get(f"{settings.chromadb_url}/api/v1/heartbeat")
            services.append({
                "name": "ChromaDB",
                "status": "ok" if r.status_code == 200 else "error",
                "detail": "RAG-Speicher",
            })
        except Exception as e:
            services.append({"name": "ChromaDB", "status": "error", "detail": str(e)})

        # 5. CalDAV
        if settings.caldav_url and settings.caldav_password:
            services.append({
                "name": "CalDAV",
                "status": "ok",
                "detail": settings.caldav_calendar,
            })
        else:
            services.append({"name": "CalDAV", "status": "off", "detail": "Nicht konfiguriert"})

    # 6. Termine count (recent)
    try:
        count = await session.execute(
            select(func.count(Termin.id)).where(Termin.datetime_ >= datetime.utcnow())
        )
        termin_total = count.scalar() or 0
        services.append({
            "name": "Termine",
            "status": "ok" if termin_total > 0 else "idle",
            "detail": f"{termin_total} anstehend",
        })
    except Exception:
        services.append({"name": "Termine", "status": "error", "detail": "DB-Fehler"})

    return {"services": services}


def _compute_status(last_heartbeat: datetime | None, error_count_24h: int) -> str:
    """Compute health status based on heartbeat age and error rate.

    Logic:
    - GREEN: heartbeat < 5 minutes ago, error_count_24h < 10
    - YELLOW: heartbeat 5-15 minutes ago OR error_count_24h 10-50
    - RED: heartbeat > 15 minutes ago OR error_count_24h > 50
    """
    now = datetime.utcnow()

    # Check heartbeat age
    if not last_heartbeat:
        return "red"

    age_minutes = (now - last_heartbeat).total_seconds() / 60

    # Determine status based on age
    if age_minutes > 15:
        status_from_age = "red"
    elif age_minutes > 5:
        status_from_age = "yellow"
    else:
        status_from_age = "green"

    # Determine status based on error rate
    if error_count_24h > 50:
        status_from_errors = "red"
    elif error_count_24h > 10:
        status_from_errors = "yellow"
    else:
        status_from_errors = "green"

    # Return worst status (red > yellow > green)
    if status_from_age == "red" or status_from_errors == "red":
        return "red"
    elif status_from_age == "yellow" or status_from_errors == "yellow":
        return "yellow"
    else:
        return "green"


@router.get("/capture-stats")
async def get_capture_stats(
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Get capture statistics for all monitored chats with computed health status.

    Returns stats from the capture_stats table with green/yellow/red status
    computed based on last heartbeat age and error count.
    """
    result = await session.execute(select(CaptureStats).order_by(desc(CaptureStats.last_heartbeat)))
    stats = result.scalars().all()

    return {
        "chats": [
            {
                "chat_id": s.chat_id,
                "last_heartbeat": s.last_heartbeat.isoformat() if s.last_heartbeat else None,
                "messages_captured_24h": s.messages_captured_24h,
                "error_count_24h": s.error_count_24h,
                "status": _compute_status(s.last_heartbeat, s.error_count_24h),
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in stats
        ],
    }


@router.get("/communication-pattern/{chat_id}")
async def get_communication_pattern(
    chat_id: str,
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Get communication pattern heatmap: weekday x hour of message frequency.

    Returns a 7x24 matrix where:
    - Rows represent weekdays (0=Monday, 6=Sunday)
    - Columns represent hours (0-23)
    - Values represent message counts for that weekday-hour combination

    This enables visualizing when conversations are most active.
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Query all messages for the chat within the time window
    result = await session.execute(
        select(Message.timestamp)
        .where(and_(Message.chat_id == chat_id, Message.timestamp >= since))
    )
    messages = result.scalars().all()

    # Initialize 7x24 heatmap matrix (weekday x hour)
    heatmap = [[0 for _ in range(24)] for _ in range(7)]

    # Populate heatmap
    for timestamp in messages:
        weekday = timestamp.weekday()  # 0=Monday, 6=Sunday
        hour = timestamp.hour
        heatmap[weekday][hour] += 1

    return {
        "chat_id": chat_id,
        "days": days,
        "heatmap": heatmap,
        "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "hours": list(range(24)),
        "total_messages": sum(sum(row) for row in heatmap),
    }


@router.get("/response-times/{chat_id}")
async def get_response_times(
    chat_id: str,
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Calculate average response times per sender.

    Analyzes the time gaps between consecutive messages to determine
    how quickly each participant responds in the conversation.

    Returns:
    - Per-sender average response time in seconds
    - Message count per sender
    - Overall conversation response metrics
    """
    since = datetime.utcnow() - timedelta(days=days)

    # Query all messages for the chat, ordered by timestamp
    result = await session.execute(
        select(Message.sender, Message.timestamp)
        .where(and_(Message.chat_id == chat_id, Message.timestamp >= since))
        .order_by(Message.timestamp)
    )
    messages = result.all()

    if len(messages) < 2:
        return {
            "chat_id": chat_id,
            "days": days,
            "response_times": [],
            "total_messages": len(messages),
            "error": "Not enough messages to calculate response times",
        }

    # Calculate response times per sender
    sender_response_times = {}  # sender -> list of response times in seconds
    sender_message_counts = {}  # sender -> total messages sent

    # Track previous message to calculate gaps
    prev_sender = None
    prev_timestamp = None

    for sender, timestamp in messages:
        # Count messages per sender
        sender_message_counts[sender] = sender_message_counts.get(sender, 0) + 1

        # Calculate response time (only when sender changes)
        if prev_sender is not None and prev_sender != sender:
            # This is a response from a different person
            response_time_seconds = (timestamp - prev_timestamp).total_seconds()

            # Only count reasonable response times (< 24 hours)
            if 0 < response_time_seconds < 86400:
                if sender not in sender_response_times:
                    sender_response_times[sender] = []
                sender_response_times[sender].append(response_time_seconds)

        prev_sender = sender
        prev_timestamp = timestamp

    # Calculate averages per sender
    response_times = []
    for sender in sender_message_counts.keys():
        times = sender_response_times.get(sender, [])
        avg_response = sum(times) / len(times) if times else None

        response_times.append({
            "sender": sender,
            "avg_response_seconds": round(avg_response, 2) if avg_response else None,
            "avg_response_minutes": round(avg_response / 60, 2) if avg_response else None,
            "response_count": len(times),
            "message_count": sender_message_counts[sender],
        })

    # Sort by average response time (fastest first)
    response_times.sort(key=lambda x: x["avg_response_seconds"] if x["avg_response_seconds"] else float('inf'))

    return {
        "chat_id": chat_id,
        "days": days,
        "response_times": response_times,
        "total_messages": len(messages),
        "total_participants": len(sender_message_counts),
    }
