"""CalDAV Sync — creates calendar events in Apple iCloud Calendar.

Uses the caldav library for proper CalDAV discovery (PROPFIND),
which is required for iCloud (numeric user IDs + calendar GUIDs).
VALARM reminders at 5d, 2d, 1d, 2h before event.
Only creates events for termine with confidence >= 0.7.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from functools import lru_cache

import caldav

from app.config import settings

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.7

VCALENDAR_TEMPLATE = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//WhatsOrga//WhatsOrga//DE
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


def _get_calendar():
    """Discover and return the target CalDAV calendar (synchronous).

    Uses PROPFIND to discover the actual calendar URL on iCloud,
    which uses numeric user IDs and GUIDs internally.
    """
    client = caldav.DAVClient(
        url=settings.caldav_url,
        username=settings.caldav_username,
        password=settings.caldav_password,
    )
    principal = client.principal()
    calendars = principal.calendars()

    target_name = settings.caldav_calendar.strip()
    for cal in calendars:
        if cal.name and cal.name.strip() == target_name:
            logger.info(f"Found CalDAV calendar '{target_name}' at {cal.url}")
            return cal

    # If exact name not found, list available and raise
    names = [c.name for c in calendars]
    raise ValueError(
        f"Calendar '{target_name}' not found. Available: {names}"
    )


def _create_event_sync(
    title: str,
    dt: datetime,
    participants: list[str],
    source_text: str,
) -> str:
    """Create a CalDAV event (synchronous, runs in thread)."""
    cal = _get_calendar()

    uid = f"radar-{uuid.uuid4()}@whatsorga"
    dtstart = dt.strftime("%Y%m%dT%H%M%S")
    dtend = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")

    description = f"Erkannt aus WhatsApp\\nTeilnehmer: {', '.join(participants)}"
    if source_text:
        safe_text = source_text[:200].replace("\n", "\\n").replace(",", "\\,")
        description += f"\\nOriginal: {safe_text}"

    vcal = VCALENDAR_TEMPLATE.format(
        uid=uid,
        dtstart=dtstart,
        dtend=dtend,
        summary=title,
        description=description,
    )

    cal.save_event(vcal)
    logger.info(f"CalDAV event created: '{title}' at {dt}")
    return uid


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

    try:
        loop = asyncio.get_event_loop()
        uid = await loop.run_in_executor(
            None,
            _create_event_sync,
            title,
            dt,
            participants,
            source_text,
        )
        return uid
    except Exception as e:
        logger.error(f"CalDAV sync error: {e}")
        return None
