"""Chat Context Init — seed EverMemOS from WhatsApp chat exports.

Endpoint: POST /api/context/init
Accepts a WhatsApp chat export (plain text) and feeds it into EverMemOS
to build the initial knowledge base (persons, facts, events, relationships).

This is the "Schritt 1" from the architecture concept — it gives the system
its initial world knowledge before real-time messages start flowing.
"""

import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.ingestion.router import verify_api_key
from app.memory.evermemos_client import memorize

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/context")


class ContextInitPayload(BaseModel):
    chat_id: str
    chat_name: str = ""
    export_text: str  # Raw WhatsApp chat export


class ContextInitResponse(BaseModel):
    status: str
    messages_processed: int
    memories_created: int


# WhatsApp export line pattern: "DD.MM.YY, HH:MM - Sender: Message"
WA_LINE_PATTERN = re.compile(
    r"(\d{1,2}\.\d{1,2}\.\d{2,4}),?\s+(\d{1,2}:\d{2})\s*[-–]\s*([^:]+):\s*(.*)"
)


@router.post("/init", response_model=ContextInitResponse)
async def init_context_from_export(
    payload: ContextInitPayload,
    _auth: None = Depends(verify_api_key),
):
    """Parse a WhatsApp chat export and feed all messages into EverMemOS.

    EverMemOS will automatically:
    - Extract persons and relationships (MemCells)
    - Build profiles (who is who)
    - Identify recurring themes
    - Store facts (birthdays, preferences, addresses)
    - Create episodic summaries

    This is a one-time operation per chat to bootstrap the knowledge base.
    Subsequent messages flow through the normal ingestion pipeline.
    """
    if not payload.export_text.strip():
        raise HTTPException(status_code=400, detail="Empty export text")

    lines = payload.export_text.strip().split("\n")
    processed = 0
    memorized = 0

    # Parse and feed messages in chronological order
    current_sender = ""
    current_text = ""
    current_ts = None

    for line in lines:
        match = WA_LINE_PATTERN.match(line.strip())

        if match:
            # Flush previous message
            if current_text and current_sender:
                result = await _memorize_export_line(
                    payload.chat_id,
                    payload.chat_name or payload.chat_id,
                    current_sender,
                    current_text.strip(),
                    current_ts or datetime.utcnow(),
                    processed,
                )
                processed += 1
                if result:
                    memorized += 1

            # Parse new message
            date_str, time_str, sender, text = match.groups()
            current_sender = sender.strip()
            current_text = text.strip()
            current_ts = _parse_wa_timestamp(date_str, time_str)

        else:
            # Continuation line (multi-line message)
            if current_text:
                current_text += " " + line.strip()

    # Flush last message
    if current_text and current_sender:
        result = await _memorize_export_line(
            payload.chat_id,
            payload.chat_name or payload.chat_id,
            current_sender,
            current_text.strip(),
            current_ts or datetime.utcnow(),
            processed,
        )
        processed += 1
        if result:
            memorized += 1

    logger.info(
        f"Context init for '{payload.chat_name}': "
        f"{processed} messages processed, {memorized} memorized"
    )

    return ContextInitResponse(
        status="ok",
        messages_processed=processed,
        memories_created=memorized,
    )


async def _memorize_export_line(
    chat_id: str,
    chat_name: str,
    sender: str,
    text: str,
    timestamp: datetime,
    index: int,
) -> dict | None:
    """Feed a single export line into EverMemOS."""
    # Skip system messages
    if sender.lower() in ["system", "whatsapp"]:
        return None
    # Skip media-only messages
    if text in ["<Medien ausgeschlossen>", "<Media omitted>", ""]:
        return None

    return await memorize(
        chat_id=chat_id,
        chat_name=chat_name,
        sender=sender,
        text=text,
        timestamp=timestamp,
        message_id=f"export_{chat_id}_{index}",
        scene="assistant",
    )


def _parse_wa_timestamp(date_str: str, time_str: str) -> datetime:
    """Parse WhatsApp export timestamp formats."""
    # Try different date formats
    for date_fmt in ["%d.%m.%y", "%d.%m.%Y", "%m/%d/%y", "%m/%d/%Y"]:
        for time_fmt in ["%H:%M", "%I:%M %p"]:
            try:
                return datetime.strptime(f"{date_str} {time_str}", f"{date_fmt} {time_fmt}")
            except ValueError:
                continue
    return datetime.utcnow()
