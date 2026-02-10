"""Dashboard API endpoints — serves data for the frontend views."""

import logging
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.storage.database import get_session, Message, Analysis, DriftSnapshot, Thread, Termin
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
            }
            for t, _ in rows
        ],
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
