"""Termin Extractor — context-aware appointment extraction from German WhatsApp text.

LLM stack: Groq 70B (primary) → Gemini 2.5 Flash (fallback).
No regex fallback — only LLMs understand context well enough.

Features:
- Chain-of-thought reasoning before JSON output
- Conversation context (surrounding messages) for multi-message understanding
- Existing termine awareness for duplicate detection and event updates
- Multi-day event support (tournaments, festivals, trips)
- Category, relevance, smart reminders, confidence, and reasoning
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


SYSTEM_PROMPT = """Du bist ein intelligentes Termin-Analyse-System für {user_name}s WhatsApp-Chat mit seiner Partnerin Marike.

FAMILIEN-KONTEXT:
- {user_name} und Marike sind ein Paar mit gemeinsamen Kindern: Enno und Romy
- ALLE Kinder-Termine (Schule, Training, Abholen, Geburtstage, Arzt, Wettkämpfe, Turniere) betreffen BEIDE Eltern → "shared"
- Wenn Marike über Enno/Romy schreibt, ist es IMMER "shared" (nicht "partner_only")
- "partner_only" NUR für Marikes eigene persönliche Termine OHNE Bezug zu {user_name} oder den Kindern

KATEGORIEN:
- "appointment": Fester Termin mit Datum (Arzt, Treffen, Training, Wettkampf, Turnier, Abholen, Geburtstag)
- "reminder": Etwas mitbringen/kaufen/besorgen (konkreter Gegenstand)
- "task": Aufgabe/Vorbereitung (packen, vorbereiten, organisieren)

RELEVANZ:
- "for_me": Nur {user_name} betrifft es
- "shared": Beide beteiligt (inkl. ALLE Kinder-Termine!)
- "partner_only": NUR Marikes persönliche Termine ohne Familie
- "affects_me": {user_name} muss etwas vorbereiten/wissen

MULTI-TAG-EVENTS:
- Turniere, Wettkämpfe, Festivals, Urlaube können MEHRERE TAGE umfassen
- Wenn mehrere Daten für dasselbe Event genannt werden (z.B. "21.02. und 22.02."), erstelle EINEN Eintrag pro Tag
- Wenn ein Zeitraum genannt wird (z.B. "vom 15. bis 18. März"), erstelle einen Eintrag für den Starttag

UHRZEITEN — KRITISCH:
- Wenn eine Uhrzeit genannt wird (z.B. "um 15 Uhr", "16:30", "ab 14 Uhr"), MUSS diese im datetime-Feld stehen
- "all_day": false wenn eine Uhrzeit dabei ist → "datetime": "YYYY-MM-DDTHH:MM"
- "all_day": true NUR wenn KEINE Uhrzeit genannt wird → "datetime": "YYYY-MM-DD"

DATUMS-REGELN:
- Verwende EXAKT das genannte Datum. "25.02." → 2026-02-25, NICHT 24. oder 26.!
- Wochentage korrekt berechnen ab dem heutigen Datum
- "nächsten Donnerstag" = der NÄCHSTE Donnerstag nach heute

DUPLIKAT-ERKENNUNG:
- Prüfe die BEREITS EXISTIERENDEN TERMINE (unten aufgelistet)
- Wenn ein Termin mit gleichem/ähnlichem Titel am gleichen Tag bereits existiert → NICHT nochmal extrahieren
- Wenn die Nachricht ein UPDATE zu einem bestehenden Termin ist (z.B. neue Uhrzeit), extrahiere mit dem aktualisierten Wert

SMARTE ERINNERUNGEN (als iCal TRIGGER):
- Einkauf: NICHT Sonntag (geschlossen in DE). Trigger: 1-2 Werktage vorher
- Packen/Vorbereiten: Vorabend 18:00-20:00. Trigger: z.B. -PT14H
- Fester Termin: -P1D und -PT2H
- Arzttermin: -P7D, -P1D, -PT2H
- Wettkampf/Turnier: -P3D, -P1D, -PT2H

{existing_termine}

{feedback_examples}

{memory_context}"""

USER_PROMPT = """Heute ist {today} ({weekday}).

{conversation_context}

AKTUELLE NACHRICHT von {sender} (diese analysieren):
"{text}"

AUFGABE: Analysiere die aktuelle Nachricht IM KONTEXT der umgebenden Nachrichten.
Denke Schritt für Schritt:
1. Enthält die Nachricht einen konkreten Termin, eine Aufgabe oder Erinnerung?
2. Wenn ja: Welches Datum/Uhrzeit? Wer ist beteiligt? Existiert der Termin schon?
3. Ist es ein neuer Termin oder ein Update zu einem bestehenden?
4. Welche Kategorie und Relevanz?

Wenn die Nachricht nur Alltagschat ist, antworte: []
Wenn ein Termin bereits in der EXISTIERENDE-TERMINE-Liste steht, antworte: []

Format als JSON-Array:
[{{
  "title": "Kurze, klare Beschreibung",
  "datetime": "YYYY-MM-DDTHH:MM oder YYYY-MM-DD bei all_day",
  "all_day": true/false,
  "participants": ["Name1"],
  "confidence": 0.0-1.0,
  "category": "appointment|reminder|task",
  "relevance": "for_me|shared|partner_only|affects_me",
  "reminders": [{{"trigger": "-P1D", "description": "..."}}],
  "reasoning": "Ausführliche Begründung: Was wurde erkannt, warum diese Einstufung, ist es neu oder Duplikat?"
}}]

NUR JSON-Array ausgeben, kein weiterer Text."""


WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


async def extract_termine(
    text: str,
    sender: str,
    timestamp: datetime,
    feedback_examples: str = "",
    memory_context: str = "",
    conversation_context: str = "",
    existing_termine: str = "",
) -> list[ExtractedTermin]:
    """Extract appointments from message text using LLM cascade (no regex fallback)."""
    if not text or len(text) < 10:
        return []

    if not _might_contain_date(text):
        return []

    # LLM cascade: Groq → Gemini (no regex fallback — too error-prone)
    results = await _extract_via_groq(text, sender, timestamp, feedback_examples, memory_context, conversation_context, existing_termine)
    if results is not None:
        return results

    results = await _extract_via_gemini(text, sender, timestamp, feedback_examples, memory_context, conversation_context, existing_termine)
    if results is not None:
        return results

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
        r'(abholen|hort|schule|kita|wettkampf|turnier|meisterschaft)',
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
    conversation_context: str = "",
    existing_termine: str = "",
) -> tuple[str, str]:
    """Build system and user prompts for LLM extraction."""
    user_name = settings.termin_user_name

    feedback_block = ""
    if feedback_examples:
        feedback_block = f"\nFEEDBACK-BEISPIELE (lerne daraus):\n{feedback_examples}"

    memory_block = ""
    if memory_context:
        memory_block = f"\nKONTEXT AUS GEDÄCHTNIS:\n{memory_context}"

    existing_block = ""
    if existing_termine:
        existing_block = f"\nBEREITS EXISTIERENDE TERMINE (nicht nochmal extrahieren!):\n{existing_termine}"

    system = SYSTEM_PROMPT.format(
        user_name=user_name,
        feedback_examples=feedback_block,
        memory_context=memory_block,
        existing_termine=existing_block,
    )

    today = timestamp.strftime("%Y-%m-%d")
    weekday = WEEKDAYS_DE[timestamp.weekday()]

    conv_block = ""
    if conversation_context:
        conv_block = f"KONVERSATIONS-KONTEXT (vorherige Nachrichten):\n{conversation_context}\n"

    user = USER_PROMPT.format(
        today=today,
        weekday=weekday,
        sender=sender,
        text=text,
        conversation_context=conv_block,
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
    conversation_context: str = "",
    existing_termine: str = "",
) -> list[ExtractedTermin] | None:
    """Use Groq llama-3.3-70b-versatile for extraction (primary)."""
    if not settings.groq_api_key:
        return None

    system_prompt, user_prompt = _build_prompts(text, sender, timestamp, feedback_examples, memory_context, conversation_context, existing_termine)

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
                    "max_tokens": 2048,
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
                    logger.info(f"Groq: '{r.title}' @ {r.datetime_str} (all_day={r.all_day}, conf={r.confidence}, rel={r.relevance}) — {r.reasoning[:200]}")
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
    conversation_context: str = "",
    existing_termine: str = "",
) -> list[ExtractedTermin] | None:
    """Use Gemini 2.5 Flash as fallback LLM."""
    if not settings.gemini_api_key:
        return None

    system_prompt, user_prompt = _build_prompts(text, sender, timestamp, feedback_examples, memory_context, conversation_context, existing_termine)
    combined_prompt = f"{system_prompt}\n\n{user_prompt}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "contents": [{"parts": [{"text": combined_prompt}]}],
                    "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
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
                    logger.info(f"Gemini: '{r.title}' @ {r.datetime_str} (all_day={r.all_day}, conf={r.confidence}, rel={r.relevance}) — {r.reasoning[:200]}")
                if not results:
                    logger.info(f"Gemini: no termine in '{text[:60]}...'")
            return results

    except Exception as e:
        logger.warning(f"Gemini termin extraction error: {e}")
        return None
