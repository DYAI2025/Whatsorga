"""CalDAV Sync — creates calendar events in Apple iCloud Calendar.

Dual-calendar system:
- "WhatsOrga" — auto-confirmed events (confidence >= threshold)
- "WhatsOrga ?" — suggested events for user review (confidence < threshold)

Dynamic VALARM reminders based on LLM-generated reminder config.
Relevance-based routing skips partner-only events.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

import caldav

from app.config import settings

logger = logging.getLogger(__name__)

# Calendar cache to avoid repeated PROPFIND discovery
_calendar_cache: dict[str, object] = {}


def _get_calendar(calendar_name: str | None = None):
    """Discover and return a CalDAV calendar by name (synchronous).

    Uses a cache to avoid repeated PROPFIND per calendar name.
    """
    name = (calendar_name or settings.caldav_calendar).strip()

    if name in _calendar_cache:
        return _calendar_cache[name]

    client = caldav.DAVClient(
        url=settings.caldav_url,
        username=settings.caldav_username,
        password=settings.caldav_password,
    )
    principal = client.principal()
    calendars = principal.calendars()

    for cal in calendars:
        if cal.name and cal.name.strip() == name:
            logger.info(f"Found CalDAV calendar '{name}' at {cal.url}")
            _calendar_cache[name] = cal
            return cal

    names = [c.name for c in calendars]
    raise ValueError(f"Calendar '{name}' not found. Available: {names}")


def _build_valarms(summary: str, reminders: list[dict] | None) -> str:
    """Build VALARM blocks from reminder config.

    If no reminders provided, falls back to default: 1 day + 2 hours before.
    """
    if not reminders:
        reminders = [
            {"trigger": "-P1D", "description": f"Morgen: {summary}"},
            {"trigger": "-PT2H", "description": f"In 2 Stunden: {summary}"},
        ]

    blocks = []
    for r in reminders:
        trigger = r.get("trigger", "-PT2H")
        desc = r.get("description", summary)
        # Sanitize description for iCal
        desc = desc.replace("\n", " ").replace("\\", "\\\\")
        blocks.append(
            f"BEGIN:VALARM\n"
            f"TRIGGER:{trigger}\n"
            f"ACTION:DISPLAY\n"
            f"DESCRIPTION:{desc}\n"
            f"END:VALARM"
        )

    return "\n".join(blocks)


def _build_vcalendar(
    uid: str,
    dtstart: str,
    dtend: str,
    summary: str,
    description: str,
    reminders: list[dict] | None = None,
) -> str:
    """Build a complete VCALENDAR string with dynamic VALARMs."""
    valarms = _build_valarms(summary, reminders)

    return (
        f"BEGIN:VCALENDAR\n"
        f"VERSION:2.0\n"
        f"PRODID:-//WhatsOrga//WhatsOrga//DE\n"
        f"BEGIN:VEVENT\n"
        f"UID:{uid}\n"
        f"DTSTART:{dtstart}\n"
        f"DTEND:{dtend}\n"
        f"SUMMARY:{summary}\n"
        f"DESCRIPTION:{description}\n"
        f"{valarms}\n"
        f"END:VEVENT\n"
        f"END:VCALENDAR"
    )


def _create_event_sync(
    title: str,
    dt: datetime,
    participants: list[str],
    source_text: str,
    calendar_name: str,
    reminders: list[dict] | None = None,
    context_note: str = "",
) -> str:
    """Create a CalDAV event (synchronous, runs in thread)."""
    cal = _get_calendar(calendar_name)

    uid = f"radar-{uuid.uuid4()}@whatsorga"
    dtstart = dt.strftime("%Y%m%dT%H%M%S")
    dtend = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")

    description = f"Erkannt aus WhatsApp\\nTeilnehmer: {', '.join(participants)}"
    if context_note:
        safe_note = context_note[:200].replace("\n", "\\n").replace(",", "\\,")
        description += f"\\nKontext: {safe_note}"
    if source_text:
        safe_text = source_text[:200].replace("\n", "\\n").replace(",", "\\,")
        description += f"\\nOriginal: {safe_text}"

    vcal = _build_vcalendar(
        uid=uid,
        dtstart=dtstart,
        dtend=dtend,
        summary=title,
        description=description,
        reminders=reminders,
    )

    cal.save_event(vcal)
    logger.info(f"CalDAV event created in '{calendar_name}': '{title}' at {dt}")
    return uid


async def sync_termin_to_calendar(
    title: str,
    dt: datetime,
    participants: list[str],
    confidence: float,
    source_text: str = "",
    relevance: str = "shared",
    reminders: list[dict] | None = None,
    context_note: str = "",
) -> tuple[str | None, str]:
    """Route termin to the appropriate calendar based on confidence and relevance.

    Returns (caldav_uid, status) tuple:
    - status: "auto" | "suggested" | "skipped"
    """
    # Skip partner-only events
    if relevance == "partner_only":
        logger.info(f"Skipping partner-only termin: '{title}'")
        return None, "skipped"

    if not settings.caldav_url or not settings.caldav_username:
        logger.warning("CalDAV not configured, skipping sync")
        return None, "skipped"

    # Determine target calendar and status
    auto_threshold = settings.termin_auto_confidence
    if confidence >= auto_threshold:
        calendar_name = settings.caldav_calendar
        status = "auto"
    else:
        calendar_name = settings.caldav_suggest_calendar
        status = "suggested"

    # Prefix title for affects_me relevance
    event_title = title
    if relevance == "affects_me":
        event_title = f"[Info] {title}"

    try:
        loop = asyncio.get_event_loop()
        uid = await loop.run_in_executor(
            None,
            _create_event_sync,
            event_title,
            dt,
            participants,
            source_text,
            calendar_name,
            reminders,
            context_note,
        )
        return uid, status
    except Exception as e:
        logger.error(f"CalDAV sync error: {e}")
        return None, status
