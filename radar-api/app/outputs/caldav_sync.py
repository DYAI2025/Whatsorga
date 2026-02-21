"""CalDAV Sync — creates calendar events in Apple iCloud Calendar.

Dual-calendar system:
- "WhatsOrga" — auto-confirmed events (confidence >= threshold)
- "WhatsOrga ?" — suggested events for user review (confidence < threshold)

Dynamic VALARM reminders based on LLM-generated reminder config.
Relevance-based routing skips partner-only events.
Supports all-day events (birthdays, holidays) and timed events with Europe/Berlin timezone.
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

TIMEZONE_BERLIN = """\
BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:STANDARD
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
END:DAYLIGHT
END:VTIMEZONE"""


def _get_calendar(calendar_name: str | None = None):
    """Discover and return a CalDAV calendar by name (synchronous)."""
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
    """Build VALARM blocks from reminder config."""
    if not reminders:
        reminders = [
            {"trigger": "-P1D", "description": f"Morgen: {summary}"},
            {"trigger": "-PT2H", "description": f"In 2 Stunden: {summary}"},
        ]

    blocks = []
    for r in reminders:
        trigger = r.get("trigger", "-PT2H")
        desc = r.get("description", summary)
        desc = desc.replace("\n", " ").replace("\\", "\\\\")
        blocks.append(
            f"BEGIN:VALARM\r\n"
            f"TRIGGER:{trigger}\r\n"
            f"ACTION:DISPLAY\r\n"
            f"DESCRIPTION:{desc}\r\n"
            f"END:VALARM"
        )

    return "\r\n".join(blocks)


def _build_vcalendar(
    uid: str,
    dtstart: str,
    dtend: str,
    summary: str,
    description: str,
    all_day: bool = False,
    reminders: list[dict] | None = None,
    location: str = "",
) -> str:
    """Build a complete VCALENDAR string with timezone and dynamic VALARMs."""
    valarms = _build_valarms(summary, reminders)

    if all_day:
        dt_lines = (
            f"DTSTART;VALUE=DATE:{dtstart}\r\n"
            f"DTEND;VALUE=DATE:{dtend}"
        )
        tz_block = ""
    else:
        dt_lines = (
            f"DTSTART;TZID=Europe/Berlin:{dtstart}\r\n"
            f"DTEND;TZID=Europe/Berlin:{dtend}"
        )
        tz_block = TIMEZONE_BERLIN + "\r\n"

    location_line = f"LOCATION:{location}\r\n" if location else ""

    return (
        f"BEGIN:VCALENDAR\r\n"
        f"VERSION:2.0\r\n"
        f"PRODID:-//WhatsOrga//WhatsOrga//DE\r\n"
        f"{tz_block}"
        f"BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"{dt_lines}\r\n"
        f"SUMMARY:{summary}\r\n"
        f"{location_line}"
        f"DESCRIPTION:{description}\r\n"
        f"{valarms}\r\n"
        f"END:VEVENT\r\n"
        f"END:VCALENDAR"
    )


def _create_event_sync(
    title: str,
    dt: datetime,
    participants: list[str],
    source_text: str,
    calendar_name: str,
    all_day: bool = False,
    reminders: list[dict] | None = None,
    context_note: str = "",
    location: str = "",
) -> str:
    """Create a CalDAV event (synchronous, runs in thread)."""
    cal = _get_calendar(calendar_name)

    uid = f"radar-{uuid.uuid4()}@whatsorga"

    if all_day:
        # All-day: DATE format YYYYMMDD, end = start + 1 day
        dtstart = dt.strftime("%Y%m%d")
        dtend = (dt + timedelta(days=1)).strftime("%Y%m%d")
    else:
        # Timed: local time format (TZID handles timezone)
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
        all_day=all_day,
        reminders=reminders,
        location=location,
    )

    cal.save_event(vcal)
    event_type = "all-day" if all_day else f"at {dt}"
    logger.info(f"CalDAV event created in '{calendar_name}': '{title}' {event_type}{f' @ {location}' if location else ''}")
    return uid


async def sync_termin_to_calendar(
    title: str,
    dt: datetime,
    participants: list[str],
    confidence: float,
    source_text: str = "",
    relevance: str = "shared",
    all_day: bool = False,
    reminders: list[dict] | None = None,
    context_note: str = "",
    location: str = "",
) -> tuple[str | None, str]:
    """Route termin to the appropriate calendar based on confidence and relevance.

    Returns (caldav_uid, status) tuple.
    """
    if relevance == "partner_only":
        logger.info(f"Skipping partner-only termin: '{title}'")
        return None, "skipped"

    if not settings.caldav_url or not settings.caldav_username:
        logger.warning("CalDAV not configured, skipping sync")
        return None, "skipped"

    auto_threshold = settings.termin_auto_confidence
    if confidence >= auto_threshold:
        calendar_name = settings.caldav_calendar
        status = "auto"
    else:
        calendar_name = settings.caldav_suggest_calendar
        status = "suggested"

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
            all_day,
            reminders,
            context_note,
            location,
        )
        return uid, status
    except Exception as e:
        logger.error(f"CalDAV sync error: {e}")
        return None, status


def _update_event_sync(
    caldav_uid: str,
    title: str,
    dt: datetime,
    participants: list[str],
    source_text: str,
    calendar_name: str,
    all_day: bool = False,
    reminders: list[dict] | None = None,
    context_note: str = "",
    location: str = "",
) -> str:
    """Update an existing CalDAV event by replacing it with new data (synchronous)."""
    cal = _get_calendar(calendar_name)

    if all_day:
        dtstart = dt.strftime("%Y%m%d")
        dtend = (dt + timedelta(days=1)).strftime("%Y%m%d")
    else:
        dtstart = dt.strftime("%Y%m%dT%H%M%S")
        dtend = (dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")

    description = f"Erkannt aus WhatsApp\\nTeilnehmer: {', '.join(participants)}"
    if context_note:
        safe_note = context_note[:200].replace("\n", "\\n").replace(",", "\\,")
        description += f"\\nKontext: {safe_note}"
    if source_text:
        safe_text = source_text[:200].replace("\n", "\\n").replace(",", "\\,")
        description += f"\\nOriginal: {safe_text}"

    # Reuse the same UID so CalDAV replaces the event
    vcal = _build_vcalendar(
        uid=caldav_uid,
        dtstart=dtstart,
        dtend=dtend,
        summary=title,
        description=description,
        all_day=all_day,
        reminders=reminders,
        location=location,
    )

    cal.save_event(vcal)
    event_type = "all-day" if all_day else f"at {dt}"
    logger.info(f"CalDAV event UPDATED in '{calendar_name}': '{title}' {event_type}{f' @ {location}' if location else ''} (uid={caldav_uid})")
    return caldav_uid


def _delete_event_sync(caldav_uid: str, calendar_name: str) -> bool:
    """Delete a single CalDAV event by UID (synchronous)."""
    cal = _get_calendar(calendar_name)
    try:
        event = cal.event_by_url(f"{cal.url}{caldav_uid}.ics")
        event.delete()
        logger.info(f"CalDAV event DELETED from '{calendar_name}': uid={caldav_uid}")
        return True
    except Exception:
        # Fallback: search all events for matching UID
        try:
            for event in cal.events():
                if caldav_uid in str(event.data):
                    event.delete()
                    logger.info(f"CalDAV event DELETED (by search) from '{calendar_name}': uid={caldav_uid}")
                    return True
        except Exception as e2:
            logger.warning(f"CalDAV delete fallback failed: {e2}")
    logger.warning(f"CalDAV event not found for delete: uid={caldav_uid}")
    return False


async def update_termin_in_calendar(
    caldav_uid: str,
    title: str,
    dt: datetime,
    participants: list[str],
    confidence: float,
    source_text: str = "",
    relevance: str = "shared",
    all_day: bool = False,
    reminders: list[dict] | None = None,
    context_note: str = "",
    location: str = "",
) -> tuple[str | None, str]:
    """Update an existing calendar event. Returns (caldav_uid, status)."""
    if not settings.caldav_url or not settings.caldav_username:
        return caldav_uid, "auto"

    auto_threshold = settings.termin_auto_confidence
    calendar_name = settings.caldav_calendar if confidence >= auto_threshold else settings.caldav_suggest_calendar
    status = "auto" if confidence >= auto_threshold else "suggested"

    event_title = f"[Info] {title}" if relevance == "affects_me" else title

    try:
        loop = asyncio.get_event_loop()
        uid = await loop.run_in_executor(
            None, _update_event_sync,
            caldav_uid, event_title, dt, participants, source_text,
            calendar_name, all_day, reminders, context_note, location,
        )
        return uid, status
    except Exception as e:
        logger.error(f"CalDAV update error: {e}")
        return caldav_uid, status


async def delete_termin_from_calendar(caldav_uid: str) -> bool:
    """Delete a single calendar event by UID."""
    if not settings.caldav_url or not settings.caldav_username or not caldav_uid:
        return False

    try:
        loop = asyncio.get_event_loop()
        # Try both calendars
        for cal_name in [settings.caldav_calendar, settings.caldav_suggest_calendar]:
            try:
                deleted = await loop.run_in_executor(None, _delete_event_sync, caldav_uid, cal_name)
                if deleted:
                    return True
            except Exception:
                continue
        return False
    except Exception as e:
        logger.error(f"CalDAV delete error: {e}")
        return False


def _delete_all_events_sync(calendar_name: str) -> int:
    """Delete all WhatsOrga events from a calendar (synchronous)."""
    cal = _get_calendar(calendar_name)
    events = cal.events()
    count = 0
    for event in events:
        try:
            event.delete()
            count += 1
        except Exception as e:
            logger.warning(f"Failed to delete event: {e}")
    # Clear cache so next sync rediscovers
    _calendar_cache.pop(calendar_name, None)
    return count


async def delete_all_calendar_events() -> dict:
    """Delete all events from both WhatsOrga calendars. Returns counts."""
    if not settings.caldav_url or not settings.caldav_username:
        return {"error": "CalDAV not configured"}

    loop = asyncio.get_event_loop()
    results = {}
    for cal_name in [settings.caldav_calendar, settings.caldav_suggest_calendar]:
        try:
            count = await loop.run_in_executor(None, _delete_all_events_sync, cal_name)
            results[cal_name] = count
            logger.info(f"Deleted {count} events from '{cal_name}'")
        except Exception as e:
            results[cal_name] = f"error: {e}"
            logger.error(f"Error clearing calendar '{cal_name}': {e}")

    return results
