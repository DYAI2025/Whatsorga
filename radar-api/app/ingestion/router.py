"""Ingestion endpoint — receives messages from the Chrome extension."""

import base64
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.storage.database import get_session, Message, Analysis, CaptureStats
from app.ingestion.audio_handler import transcribe_audio
from sqlalchemy import select
from app.analysis.marker_engine import analyze_markers
from app.analysis.sentiment_tracker import score_sentiment
from app.analysis.weaver import process_message_context
from app.analysis.termin_extractor import extract_termine
from app.analysis.semantic_transcriber import enrich_transcript
from app.outputs.caldav_sync import sync_termin_to_calendar
from app.storage.database import Termin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class IncomingMessage(BaseModel):
    messageId: str
    sender: str
    text: str = ""
    timestamp: str | None = None
    chatId: str = "unknown"
    chatName: str = "Unknown"
    replyTo: str | None = None
    hasAudio: bool = False
    audioBlob: str | None = None  # base64


class IngestPayload(BaseModel):
    messages: list[IncomingMessage]


class IngestResponse(BaseModel):
    accepted: int
    errors: int


def verify_api_key(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[7:]
    if token != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


@router.post("/ingest", response_model=IngestResponse)
async def ingest_messages(
    payload: IngestPayload,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    accepted = 0
    errors = 0

    for msg in payload.messages:
        try:
            # Parse timestamp
            ts = _parse_timestamp(msg.timestamp)

            # Handle audio transcription
            text = msg.text
            audio_path = None
            is_transcribed = False

            if msg.hasAudio and msg.audioBlob:
                transcript = await transcribe_audio(msg.audioBlob)
                if transcript:
                    text = transcript
                    is_transcribed = True

            # Store in DB
            db_msg = Message(
                chat_id=msg.chatId,
                chat_name=msg.chatName,
                sender=msg.sender,
                text=text or None,
                timestamp=ts,
                audio_path=audio_path,
                is_transcribed=is_transcribed,
                raw_payload={
                    "messageId": msg.messageId,
                    "replyTo": msg.replyTo,
                    "hasAudio": msg.hasAudio,
                },
            )
            session.add(db_msg)
            await session.flush()  # get db_msg.id

            # Run analysis (marker engine + sentiment)
            if text:
                marker_result = analyze_markers(text)
                sentiment_result = score_sentiment(text)

                analysis = Analysis(
                    message_id=db_msg.id,
                    sentiment_score=sentiment_result.score,
                    markers=marker_result.raw_counts,
                    marker_categories={
                        "dominant": marker_result.dominant,
                        "categories": marker_result.categories,
                        "scores": marker_result.markers,
                        "sentiment_label": sentiment_result.label,
                    },
                )
                session.add(analysis)

                # RAG embed + thread update (non-blocking on failure)
                try:
                    await process_message_context(
                        session, db_msg.id, msg.chatId, text,
                        msg.sender, ts, sentiment_result.score,
                        {"dominant": marker_result.dominant, "categories": marker_result.categories},
                    )
                except Exception as e:
                    logger.warning(f"Weaver/RAG error (non-fatal): {e}")

                # Termin extraction + CalDAV sync
                try:
                    termine = await extract_termine(text, msg.sender, ts)
                    for t in termine:
                        termin_dt = datetime.fromisoformat(t.datetime_str) if t.datetime_str else None
                        if not termin_dt:
                            continue

                        # Sync to Apple Calendar
                        caldav_uid = await sync_termin_to_calendar(
                            t.title, termin_dt, t.participants, t.confidence, text,
                        )

                        # Store in DB
                        db_termin = Termin(
                            message_id=db_msg.id,
                            title=t.title,
                            datetime_=termin_dt,
                            participants=t.participants,
                            confidence=t.confidence,
                            caldav_uid=caldav_uid,
                        )
                        session.add(db_termin)
                except Exception as e:
                    logger.warning(f"Termin extraction error (non-fatal): {e}")

            accepted += 1

        except Exception as e:
            logger.error(f"Error processing message {msg.messageId}: {e}")
            errors += 1

    if accepted > 0:
        await session.commit()

    logger.info(f"Ingested {accepted} messages ({errors} errors)")
    return IngestResponse(accepted=accepted, errors=errors)


def _parse_timestamp(ts_str: str | None) -> datetime:
    if not ts_str:
        return datetime.utcnow()

    # Try ISO format (from content.js: "2026-02-10T14:23:00")
    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"]:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue

    # Fallback
    return datetime.utcnow()


@router.post("/transcribe")
async def transcribe_endpoint(
    audio: UploadFile = File(...),
    chat_id: str = Form("unknown"),
    sender: str = Form("Unknown"),
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Standalone transcription + semantic enrichment endpoint.

    Accepts an audio file upload, transcribes via Groq Whisper,
    enriches with conversation context, and returns the full result.

    Usage:
        curl -X POST http://localhost:8900/api/transcribe \
          -H "Authorization: Bearer $KEY" \
          -F "audio=@test.ogg" -F "chat_id=test" -F "sender=Ben"
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    audio_b64 = base64.b64encode(audio_bytes).decode()

    # Step 1: Transcribe
    raw_transcript = await transcribe_audio(audio_b64)
    if not raw_transcript:
        raise HTTPException(status_code=422, detail="Transcription failed")

    # Step 2: Semantic enrichment
    ts = datetime.utcnow()
    enriched = await enrich_transcript(session, raw_transcript, chat_id, sender, ts)

    return {
        "raw_transcript": enriched.raw,
        "enriched_transcript": enriched.enriched,
        "summary": enriched.summary,
        "topics": enriched.topics,
        "confidence": enriched.confidence,
    }


class HeartbeatPayload(BaseModel):
    chatId: str
    messageCount: int
    queueSize: int
    timestamp: str


@router.post("/heartbeat")
async def receive_heartbeat(
    payload: HeartbeatPayload,
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(verify_api_key),
):
    """Receive heartbeat from extension with capture stats."""

    # Upsert capture_stats
    result = await session.execute(
        select(CaptureStats).where(CaptureStats.chat_id == payload.chatId)
    )
    stats = result.scalar_one_or_none()

    if stats:
        stats.last_heartbeat = datetime.utcnow()
        stats.messages_captured_24h += payload.messageCount
        stats.updated_at = datetime.utcnow()
    else:
        stats = CaptureStats(
            chat_id=payload.chatId,
            last_heartbeat=datetime.utcnow(),
            messages_captured_24h=payload.messageCount,
            error_count_24h=0,
        )
        session.add(stats)

    await session.commit()

    logger.info(f"Heartbeat received for {payload.chatId}: +{payload.messageCount} messages")
    return {"status": "ok"}
