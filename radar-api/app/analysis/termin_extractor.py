"""Termin Extractor — extracts dates/appointments from German WhatsApp text.

LLM stack: Groq 70B (primary) → Gemini 2.5 Flash (fallback).
No regex fallback — only LLMs understand context well enough.
Extracts category, relevance, smart reminders, confidence, and reasoning.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTermin:
    title: str
    datetime_str: str  # ISO format YYYY-MM-DDTHH:MM or YYYY-MM-DD for all-day
    participants: list[str]
    confidence: float  # 0.0 - 1.0
    category: str = "appointment"  # appointment | reminder | task
    relevance: str = "shared"  # for_me | shared | partner_only | affects_me
    reminders: list[dict] = field(default_factory=list)
    context_note: str = ""
    all_day: bool = False
    reasoning: str = ""


SYSTEM_PROMPT = """Du bist ein intelligentes Termin-System für die WhatsApp-Kommunikation zwischen {user_name} und seiner Partnerin Marike.

FAMILIEN-KONTEXT:
- {user_name} und Marike sind ein Paar mit gemeinsamen Kindern: Enno und Romy
- Alle Kinder-Termine (Schule, Training, Abholen, Geburtstage, Arzt) betreffen BEIDE Eltern
- Wenn Marike schreibt "Enno hat Training" oder "Romy abholen", muss {user_name} das oft organisieren/wissen
- Termine die nur Marikes eigene Aktivitäten betreffen (Yoga, Friseur, Treffen mit Freundinnen OHNE {user_name}) = "partner_only"

KATEGORIEN:
- "appointment": Fester Termin mit Datum/Uhrzeit (Arzt, Treffen, Training, Abholen)
- "reminder": Etwas mitbringen/kaufen/besorgen
- "task": Aufgabe/Vorbereitung (packen, vorbereiten, organisieren)

RELEVANZ:
- "for_me": Nur {user_name} betrifft es
- "shared": Beide beteiligt (inkl. Kinder-Termine!)
- "partner_only": NUR Marikes eigene Termine ohne Bezug zu {user_name} oder den Kindern
- "affects_me": {user_name} muss etwas vorbereiten/wissen

UHRZEITEN — KRITISCH:
- Wenn eine Uhrzeit genannt wird (z.B. "um 15 Uhr", "16:30", "ab 14 Uhr"), MUSS diese im datetime-Feld stehen
- "all_day": false wenn eine Uhrzeit dabei ist, "datetime": "YYYY-MM-DDTHH:MM"
- "all_day": true NUR wenn KEINE Uhrzeit genannt wird (Geburtstag, Feiertag, ganztägig)
- Bei all_day: true ist datetime nur "YYYY-MM-DD"

DATUMS-REGELN:
- Verwende EXAKT das genannte Datum. Wenn "25.02." gesagt wird → 2026-02-25, NICHT 24. oder 26.!
- Wochentage korrekt berechnen ab dem heutigen Datum

SMARTE ERINNERUNGEN (als iCal TRIGGER):
- Einkauf: NICHT Sonntag (geschlossen in DE). Trigger: 1-2 Werktage vorher
- Packen/Vorbereiten: Vorabend 18:00-20:00. Trigger: z.B. -PT14H
- Fester Termin: -P1D und -PT2H
- Arzttermin: -P7D, -P1D, -PT2H

{feedback_examples}

{memory_context}"""

USER_PROMPT = """Heute ist {today} ({weekday}).
Nachricht von {sender}:
"{text}"

Analysiere diese Nachricht im Kontext der Beziehung von Ben und Marike.
Extrahiere Termine, Aufgaben und Erinnerungen als JSON-Array.
Wenn kein Termin enthalten ist: []

Format pro Eintrag:
[{{
  "title": "Kurze, klare Beschreibung",
  "datetime": "YYYY-MM-DDTHH:MM oder YYYY-MM-DD bei all_day",
  "all_day": false,
  "participants": ["Name1"],
  "confidence": 0.0-1.0,
  "category": "appointment|reminder|task",
  "relevance": "for_me|shared|partner_only|affects_me",
  "reminders": [{{"trigger": "-P1D", "description": "..."}}],
  "reasoning": "Kurze Begründung warum extrahiert und wie eingestuft"
}}]

NUR JSON-Array ausgeben, kein weiterer Text."""


WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


async def extract_termine(
    text: str,
    sender: str,
    timestamp: datetime,
    feedback_examples: str = "",
    memory_context: str = "",
) -> list[ExtractedTermin]:
    """Extract appointments from message text using LLM cascade (no regex fallback)."""
    if not text or len(text) < 10:
        return []

    if not _might_contain_date(text):
        return []

    # LLM cascade: Groq → Gemini (no regex fallback — too error-prone)
    results = await _extract_via_groq(text, sender, timestamp, feedback_examples, memory_context)
    if results is not None:
        return results

    results = await _extract_via_gemini(text, sender, timestamp, feedback_examples, memory_context)
    if results is not None:
        return results

    # No Ollama, no regex — if both LLMs fail, skip
    logger.info(f"No LLM available for termin extraction, skipping: '{text[:60]}...'")
    return []


def _might_contain_date(text: str) -> bool:
    """Quick check if text might contain date/time or task references."""
    patterns = [
        r'\d{1,2}\.\d{1,2}\.',  # 14.02. (needs trailing dot to distinguish from decimals)
        r'\d{1,2}:\d{2}',  # 10:00, 14:30
        r'(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)',
        r'(morgen|übermorgen|nächste|kommende)',
        r'(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)',
        r'(termin|treffen|arzt|zahnarzt|kinderarzt|meeting|verabredung|training|geburtstag)',
        r'(abholen|hort|schule|kita|wettkampf)',
        r'um \d{1,2}\s*(uhr)?',  # "um 10", "um 14 uhr"
        r'ab \d{1,2}\s*(uhr)?',  # "ab 14 Uhr"
        r'(mitbring|kaufen|einkauf|besorgen|pack|vorbereiten)',
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

        # Safety: if all_day is false but datetime has no time, add default 09:00
        if not all_day and dt_str and "T" not in dt_str:
            dt_str = f"{dt_str}T09:00"
            logger.warning(f"Added default time 09:00 to non-all-day termin: '{item.get('title')}'")

        reasoning = item.get("reasoning", item.get("context_note", ""))

        results.append(ExtractedTermin(
            title=item.get("title", "Termin"),
            datetime_str=dt_str,
            participants=item.get("participants", [sender]),
            confidence=float(item.get("confidence", 0.5)),
            category=item.get("category", "appointment"),
            relevance=relevance,
            reminders=reminders,
            context_note=item.get("context_note", reasoning),
            all_day=all_day,
            reasoning=reasoning,
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
            logger.debug(f"Groq raw response: {response_text[:500]}")
            results = _parse_extraction_response(response_text, sender)

            if results is not None:
                for r in results:
                    logger.info(f"Groq: '{r.title}' @ {r.datetime_str} (all_day={r.all_day}, conf={r.confidence}, rel={r.relevance}) — {r.reasoning}")
                if not results:
                    logger.info(f"Groq: no termine in '{text[:60]}...'")
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
    """Use Gemini 2.5 Flash as fallback LLM."""
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
            logger.debug(f"Gemini raw response: {response_text[:500]}")
            results = _parse_extraction_response(response_text, sender)

            if results is not None:
                for r in results:
                    logger.info(f"Gemini: '{r.title}' @ {r.datetime_str} (all_day={r.all_day}, conf={r.confidence}, rel={r.relevance}) — {r.reasoning}")
                if not results:
                    logger.info(f"Gemini: no termine in '{text[:60]}...'")
            return results

    except Exception as e:
        logger.warning(f"Gemini termin extraction error: {e}")
        return None
