"""Termin Extractor — extracts dates/appointments from German text using Ollama.

Sends text to local Ollama (llama3.1:8b) with a prompt to extract dates.
Falls back to regex patterns if Ollama is unavailable.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTermin:
    title: str
    datetime_str: str  # ISO format
    participants: list[str]
    confidence: float  # 0.0 - 1.0


OLLAMA_PROMPT = """Extrahiere Termine aus dieser WhatsApp-Nachricht.
Antworte NUR mit einem JSON-Array. Wenn kein Termin enthalten ist, antworte mit [].

Format pro Termin:
{{"title": "kurze Beschreibung", "datetime": "YYYY-MM-DDTHH:MM", "participants": ["Name1"], "confidence": 0.0-1.0}}

Heute ist {today}. Nachricht von {sender}:
"{text}"

JSON-Array:"""


async def extract_termine(
    text: str,
    sender: str,
    timestamp: datetime,
) -> list[ExtractedTermin]:
    """Extract appointments from message text."""
    if not text or len(text) < 10:
        return []

    # Quick pre-filter: skip messages unlikely to contain dates
    if not _might_contain_date(text):
        return []

    # Try Ollama first
    results = await _extract_via_ollama(text, sender, timestamp)
    if results is not None:
        return results

    # Fallback: regex patterns
    return _extract_via_regex(text, sender, timestamp)


def _might_contain_date(text: str) -> bool:
    """Quick check if text might contain date/time references."""
    patterns = [
        r'\d{1,2}\.\d{1,2}',  # 14.02, 10.2.2026
        r'\d{1,2}:\d{2}',  # 10:00, 14:30
        r'(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)',
        r'(morgen|übermorgen|nächste|kommende)',
        r'(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)',
        r'(termin|treffen|arzt|zahnarzt|kinderarzt|meeting|verabredung|abendessen|mittag)',
        r'um \d{1,2}',  # "um 10", "um 14 uhr"
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


async def _extract_via_ollama(
    text: str, sender: str, timestamp: datetime
) -> list[ExtractedTermin] | None:
    """Use Ollama to extract appointments."""
    if not settings.ollama_url:
        return None

    today = timestamp.strftime("%Y-%m-%d (%A)")
    prompt = OLLAMA_PROMPT.format(today=today, sender=sender, text=text)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )

            if resp.status_code != 200:
                logger.warning(f"Ollama error: {resp.status_code}")
                return None

            response_text = resp.json().get("response", "").strip()

            # Parse JSON from response
            # Try to extract JSON array even if surrounded by text
            match = re.search(r'\[.*\]', response_text, re.DOTALL)
            if not match:
                return []

            items = json.loads(match.group())
            results = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                results.append(ExtractedTermin(
                    title=item.get("title", "Termin"),
                    datetime_str=item.get("datetime", ""),
                    participants=item.get("participants", [sender]),
                    confidence=float(item.get("confidence", 0.5)),
                ))
            return results

    except json.JSONDecodeError:
        logger.warning("Ollama returned invalid JSON for termin extraction")
        return []
    except Exception as e:
        logger.warning(f"Ollama termin extraction error: {e}")
        return None


def _extract_via_regex(
    text: str, sender: str, timestamp: datetime
) -> list[ExtractedTermin]:
    """Fallback: extract dates via German regex patterns."""
    results = []
    text_lower = text.lower()

    # Pattern: "am 14.02. um 10:00" or "14.2. 10 Uhr"
    date_time_pattern = re.compile(
        r'(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?\s*'
        r'(?:um\s+)?(\d{1,2})[:\.]?(\d{2})?\s*(?:uhr)?',
        re.IGNORECASE
    )

    for m in date_time_pattern.finditer(text):
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else timestamp.year
        if year < 100:
            year += 2000
        hour = int(m.group(4))
        minute = int(m.group(5)) if m.group(5) else 0

        try:
            dt = datetime(year, month, day, hour, minute)
            # Extract context around match for title
            start = max(0, m.start() - 30)
            end = min(len(text), m.end() + 30)
            context = text[start:end].strip()

            results.append(ExtractedTermin(
                title=context[:60],
                datetime_str=dt.strftime("%Y-%m-%dT%H:%M"),
                participants=[sender],
                confidence=0.6,
            ))
        except ValueError:
            continue

    # Pattern: "morgen um 10"
    tomorrow_pattern = re.compile(
        r'morgen\s+(?:um\s+)?(\d{1,2})[:\.]?(\d{2})?\s*(?:uhr)?',
        re.IGNORECASE
    )
    for m in tomorrow_pattern.finditer(text):
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        dt = timestamp + timedelta(days=1)
        dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)

        start = max(0, m.start() - 30)
        end = min(len(text), m.end() + 30)
        context = text[start:end].strip()

        results.append(ExtractedTermin(
            title=context[:60],
            datetime_str=dt.strftime("%Y-%m-%dT%H:%M"),
            participants=[sender],
            confidence=0.5,
        ))

    return results
