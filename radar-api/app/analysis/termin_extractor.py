"""Termin Extractor — extracts dates/appointments from German WhatsApp text.

LLM stack: Groq 70B (primary) → Gemini (fallback) → Ollama 8B → Regex.
Extracts category (appointment/reminder/task), relevance (for_me/shared/partner_only/affects_me),
smart reminders with context-aware timing, and confidence scoring.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTermin:
    title: str
    datetime_str: str  # ISO format or YYYY-MM-DD for all-day
    participants: list[str]
    confidence: float  # 0.0 - 1.0
    category: str = "appointment"  # appointment | reminder | task
    relevance: str = "shared"  # for_me | shared | partner_only | affects_me
    reminders: list[dict] = field(default_factory=list)
    context_note: str = ""
    all_day: bool = False


SYSTEM_PROMPT = """Du bist ein Termin-Extraktions-System für deutschsprachige WhatsApp-Nachrichten aus der Perspektive von {user_name}.

KATEGORIEN:
- "appointment": Fester Termin mit Datum/Uhrzeit (Arzt, Treffen, Meeting)
- "reminder": Etwas mitbringen/kaufen/besorgen für einen Anlass
- "task": Aufgabe/Vorbereitung (packen, vorbereiten, organisieren)

RELEVANZ für {user_name}:
- "for_me": Nur {user_name} betrifft es
- "shared": Beide beteiligt
- "partner_only": Nur Partner-Termin, {user_name} muss nichts tun → SKIP
- "affects_me": Partner-Termin aber {user_name} muss etwas vorbereiten/wissen

SMARTE ERINNERUNGEN (als iCal TRIGGER):
- Einkauf/Besorgen: NICHT Sonntag setzen (Geschäfte geschlossen in DE), stattdessen Samstag oder Freitag. Trigger: 1-2 Werktage vorher
- Packen/Vorbereiten: Vorabend zwischen 18:00-20:00. Trigger: z.B. -PT14H (14 Stunden vorher)
- Fester Termin: 1 Tag vorher + 2 Stunden vorher. Trigger: -P1D und -PT2H
- Arzttermin/Wichtig: Zusätzlich 1 Woche vorher. Trigger: -P7D, -P1D, -PT2H

{feedback_examples}

{memory_context}"""

USER_PROMPT = """Heute ist {today} ({weekday}).
Nachricht von {sender}:
"{text}"

Extrahiere alle Termine, Aufgaben und Erinnerungen als JSON-Array.
Wenn kein Termin enthalten ist: []

Format pro Eintrag:
[{{
  "title": "Kurze Beschreibung",
  "datetime": "YYYY-MM-DDTHH:MM",
  "all_day": false,
  "participants": ["Name1"],
  "confidence": 0.0-1.0,
  "category": "appointment|reminder|task",
  "relevance": "for_me|shared|partner_only|affects_me",
  "reminders": [{{"trigger": "-P1D", "description": "Morgen: ..."}}, {{"trigger": "-PT2H", "description": "In 2h: ..."}}],
  "context_note": "Warum dieser Termin extrahiert wurde"
}}]

WICHTIGE REGELN:
- "all_day": true wenn KEINE Uhrzeit genannt wird (Geburtstag, Feiertag, Urlaub, ganztägiges Event)
- "all_day": false wenn eine Uhrzeit dabei ist
- Bei "all_day": true ist "datetime" nur das Datum: "YYYY-MM-DD" (OHNE Uhrzeit)
- Geburtstage IMMER als all_day: true
- Datums-Berechnung GENAU prüfen: Wenn heute {today} ({weekday}) ist, dann ist Mittwoch = der nächste Mittwoch ab heute
- NIEMALS einen Tag abziehen! Das Datum muss EXAKT dem genannten Datum entsprechen

NUR JSON-Array ausgeben, kein weiterer Text."""


WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


async def extract_termine(
    text: str,
    sender: str,
    timestamp: datetime,
    feedback_examples: str = "",
    memory_context: str = "",
) -> list[ExtractedTermin]:
    """Extract appointments from message text using LLM cascade."""
    if not text or len(text) < 10:
        return []

    if not _might_contain_date(text):
        return []

    # LLM cascade: Groq → Gemini → Ollama → Regex
    results = await _extract_via_groq(text, sender, timestamp, feedback_examples, memory_context)
    if results is not None:
        return results

    results = await _extract_via_gemini(text, sender, timestamp, feedback_examples, memory_context)
    if results is not None:
        return results

    results = await _extract_via_ollama(text, sender, timestamp)
    if results is not None:
        return results

    return _extract_via_regex(text, sender, timestamp)


def _might_contain_date(text: str) -> bool:
    """Quick check if text might contain date/time or task references."""
    patterns = [
        r'\d{1,2}\.\d{1,2}',  # 14.02, 10.2.2026
        r'\d{1,2}:\d{2}',  # 10:00, 14:30
        r'(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)',
        r'(morgen|übermorgen|nächste|kommende)',
        r'(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)',
        r'(termin|treffen|arzt|zahnarzt|kinderarzt|meeting|verabredung|abendessen|mittag)',
        r'um \d{1,2}',  # "um 10", "um 14 uhr"
        # Task/reminder keywords
        r'(mitbring|kaufen|einkauf|besorgen|pack|vorbereiten|hol\b|bring)',
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)


def _build_prompts(
    text: str,
    sender: str,
    timestamp: datetime,
    feedback_examples: str = "",
    memory_context: str = "",
) -> tuple[str, str]:
    """Build system and user prompts for LLM extraction."""
    user_name = settings.termin_user_name

    feedback_block = ""
    if feedback_examples:
        feedback_block = f"\nFEEDBACK-BEISPIELE (lerne daraus):\n{feedback_examples}"

    memory_block = ""
    if memory_context:
        memory_block = f"\nKONTEXT AUS GEDÄCHTNIS:\n{memory_context}"

    system = SYSTEM_PROMPT.format(
        user_name=user_name,
        feedback_examples=feedback_block,
        memory_context=memory_block,
    )

    today = timestamp.strftime("%Y-%m-%d")
    weekday = WEEKDAYS_DE[timestamp.weekday()]
    user = USER_PROMPT.format(
        today=today,
        weekday=weekday,
        sender=sender,
        text=text,
    )

    return system, user


def _parse_extraction_response(response_text: str, sender: str) -> list[ExtractedTermin] | None:
    """Universal parser that handles JSON array and {"termine": [...]} wrapper."""
    if not response_text:
        return []

    response_text = response_text.strip()

    # Try to extract JSON array
    parsed = None

    # 1. Try {"termine": [...]} wrapper
    wrapper_match = re.search(r'\{\s*"termine"\s*:\s*(\[.*?\])\s*\}', response_text, re.DOTALL)
    if wrapper_match:
        try:
            parsed = json.loads(wrapper_match.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Try raw JSON array
    if parsed is None:
        array_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if array_match:
            try:
                parsed = json.loads(array_match.group())
            except json.JSONDecodeError:
                return None

    if parsed is None:
        return None

    if not isinstance(parsed, list):
        return []

    results = []
    for item in parsed:
        if not isinstance(item, dict):
            continue

        # Skip partner_only at extraction level
        relevance = item.get("relevance", "shared")

        reminders = item.get("reminders", [])
        if not isinstance(reminders, list):
            reminders = []

        # Detect all-day events
        all_day = bool(item.get("all_day", False))
        dt_str = item.get("datetime", "")
        # If datetime has no time component (YYYY-MM-DD only), treat as all-day
        if dt_str and "T" not in dt_str and len(dt_str) == 10:
            all_day = True

        results.append(ExtractedTermin(
            title=item.get("title", "Termin"),
            datetime_str=dt_str,
            participants=item.get("participants", [sender]),
            confidence=float(item.get("confidence", 0.5)),
            category=item.get("category", "appointment"),
            relevance=relevance,
            reminders=reminders,
            context_note=item.get("context_note", ""),
            all_day=all_day,
        ))

    return results


async def _extract_via_groq(
    text: str,
    sender: str,
    timestamp: datetime,
    feedback_examples: str = "",
    memory_context: str = "",
) -> list[ExtractedTermin] | None:
    """Use Groq llama-3.3-70b-versatile for extraction (primary)."""
    if not settings.groq_api_key:
        return None

    system_prompt, user_prompt = _build_prompts(text, sender, timestamp, feedback_examples, memory_context)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1024,
                },
            )

            if resp.status_code != 200:
                logger.warning(f"Groq termin error: {resp.status_code} {resp.text[:200]}")
                return None

            response_text = resp.json()["choices"][0]["message"]["content"]
            results = _parse_extraction_response(response_text, sender)

            if results is not None:
                logger.info(f"Groq extracted {len(results)} termine from: '{text[:60]}...'")
            return results

    except Exception as e:
        logger.warning(f"Groq termin extraction error: {e}")
        return None


async def _extract_via_gemini(
    text: str,
    sender: str,
    timestamp: datetime,
    feedback_examples: str = "",
    memory_context: str = "",
) -> list[ExtractedTermin] | None:
    """Use Gemini as fallback LLM."""
    if not settings.gemini_api_key:
        return None

    system_prompt, user_prompt = _build_prompts(text, sender, timestamp, feedback_examples, memory_context)
    combined_prompt = f"{system_prompt}\n\n{user_prompt}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "contents": [{"parts": [{"text": combined_prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
                },
            )

            if resp.status_code != 200:
                logger.warning(f"Gemini termin error: {resp.status_code}")
                return None

            candidates = resp.json().get("candidates", [])
            if not candidates:
                return []

            response_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            results = _parse_extraction_response(response_text, sender)

            if results is not None:
                logger.info(f"Gemini extracted {len(results)} termine")
            return results

    except Exception as e:
        logger.warning(f"Gemini termin extraction error: {e}")
        return None


async def _extract_via_ollama(
    text: str, sender: str, timestamp: datetime
) -> list[ExtractedTermin] | None:
    """Use local Ollama as last LLM fallback (no smart features)."""
    if not settings.ollama_url:
        return None

    today = timestamp.strftime("%Y-%m-%d (%A)")
    prompt = f"""Extrahiere Termine aus dieser WhatsApp-Nachricht.
Antworte NUR mit einem JSON-Array. Wenn kein Termin enthalten ist, antworte mit [].

Format pro Termin:
{{"title": "kurze Beschreibung", "datetime": "YYYY-MM-DDTHH:MM", "participants": ["Name1"], "confidence": 0.0-1.0}}

Heute ist {today}. Nachricht von {sender}:
"{text}"

JSON-Array:"""

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
