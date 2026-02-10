"""CalDAV Sync — creates calendar events in Apple iCloud Calendar.

Uses VCALENDAR format with VALARM reminders at 5d, 2d, 1d, 2h before event.
Only creates events for termine with confidence >= 0.7.
"""

import logging
import uuid
from datetime import datetime, timedelta

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.7

VCALENDAR_TEMPLATE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Beziehungs-Radar//DE
BEGIN:VEVENT
UID:{uid}
DTSTART:{dtstart}
DTEND:{dtend}
SUMMARY:{summary}
DESCRIPTION:{description}
BEGIN:VALARM
TRIGGER:-P5D
ACTION:DISPLAY
DESCRIPTION:In 5 Tagen: {summary}
END:VALARM
BEGIN:VALARM
TRIGGER:-P2D
ACTION:DISPLAY
DESCRIPTION:In 2 Tagen: {summary}
END:VALARM
BEGIN:VALARM
TRIGGER:-P1D
ACTION:DISPLAY
DESCRIPTION:Morgen: {summary}
END:VALARM
BEGIN:VALARM
TRIGGER:-PT2H
ACTION:DISPLAY
DESCRIPTION:In 2 Stunden: {summary}
END:VALARM
END:VEVENT
END:VCALENDAR"""


async def sync_termin_to_calendar(
    title: str,
    dt: datetime,
    participants: list[str],
    confidence: float,
    source_text: str = "",
) -> str | None:
    """Create a CalDAV event in Apple Calendar. Returns the UID or None."""
    if confidence < MIN_CONFIDENCE:
        logger.info(f"Skipping termin '{title}' (confidence {confidence:.2f} < {MIN_CONFIDENCE})")
        return None

    if not settings.caldav_url or not settings.caldav_username:
        logger.warning("CalDAV not configured, skipping sync")
        return None

    uid = f"radar-{uuid.uuid4()}@beziehungs-radar"
    dtstart = dt.strftime("%Y%m%dT%H%M%S")
    dtend = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")
    description = f"Erkannt aus WhatsApp\\nTeilnehmer: {', '.join(participants)}"
    if source_text:
        # Escape for VCALENDAR
        safe_text = source_text[:200].replace("\n", "\\n").replace(",", "\\,")
        description += f"\\nOriginal: {safe_text}"

    vcal = VCALENDAR_TEMPLATE.format(
        uid=uid,
        dtstart=dtstart,
        dtend=dtend,
        summary=title,
        description=description,
    )

    # PUT to CalDAV server
    calendar_path = f"/calendars/{settings.caldav_username}/{settings.caldav_calendar}/{uid}.ics"
    url = f"{settings.caldav_url.rstrip('/')}{calendar_path}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.put(
                url,
                content=vcal,
                headers={"Content-Type": "text/calendar; charset=utf-8"},
                auth=(settings.caldav_username, settings.caldav_password),
            )

            if resp.status_code in (200, 201, 204):
                logger.info(f"CalDAV event created: {title} at {dt}")
                return uid
            else:
                logger.warning(f"CalDAV PUT failed: {resp.status_code} {resp.text[:200]}")
                return None

    except Exception as e:
        logger.error(f"CalDAV sync error: {e}")
        return None
