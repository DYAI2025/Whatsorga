"""Termin Extractor — multi-dimensional reasoning for German WhatsApp messages.

LLM stack: Groq 70B (primary) → Gemini 2.5 Flash (fallback).
No regex fallback — only LLMs understand context well enough.

Uses Structured Multi-Dimensional Reasoning (Tree-of-Thoughts inspired):
The LLM evaluates each message across 6 dimensions before deciding,
giving ToT-quality reasoning in a single LLM call.
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


SYSTEM_PROMPT = """Du bist ein tiefdenkendes Termin-Analyse-System für {user_name}s WhatsApp-Chat mit Partnerin Marike.
Du analysierst NICHT oberflächlich — du denkst in DIMENSIONEN bevor du entscheidest.

═══ FAMILIEN-KONTEXT ═══
- {user_name} und Marike: Paar mit Kindern Enno und Romy
- ALLE Kinder-Termine betreffen BEIDE Eltern → "shared"
- "partner_only" NUR für Marikes rein persönliche Termine OHNE Familie

═══ MULTI-DIMENSIONALE ANALYSE ═══

Du MUSST jede Nachricht durch diese 6 Dimensionen bewerten bevor du entscheidest:

📅 DIMENSION 1 — ZEIT
- Enthält die Nachricht ein konkretes Datum oder eine Uhrzeit?
- Ist es ein Wochentag, ein relatives Datum ("morgen", "nächste Woche")?
- ACHTUNG: Zahlen im Chat sind NICHT immer Uhrzeiten! "15:46" in einer Nachricht ist oft der Zeitstempel, nicht ein Termin.
- Datum exakt übernehmen: "25.02." → 2026-02-25. Wochentage ab heute berechnen.

🏠 DIMENSION 2 — FAMILIE & RELEVANZ
- Betrifft es die Kinder? → "shared" (IMMER, egal wer schreibt)
- Nur Marike persönlich (Yoga, Friseur, Freundinnen)? → "partner_only"
- {user_name} muss etwas vorbereiten/wissen? → "affects_me"
- Beide direkt beteiligt? → "shared"

🎯 DIMENSION 3 — HANDLUNGSBEDARF
- Muss jemand irgendwo HINGEHEN? → "appointment"
- Muss etwas GEKAUFT/MITGEBRACHT werden? → "reminder"
- Muss etwas VORBEREITET/ORGANISIERT werden? → "task"
- Ist es nur INFORMATION ohne Handlung? → vielleicht kein Termin!

🔄 DIMENSION 4 — KONTEXT & DUPLIKATE
- Wurde dasselbe Thema in den vorherigen Nachrichten schon besprochen?
- Existiert der Termin bereits in der DB-Liste? → NICHT nochmal extrahieren!
- Ist es ein UPDATE (neue Uhrzeit, Absage)? → Extrahiere nur das Update
- Wird das gleiche Event mehrfach erwähnt? → Nur EINMAL extrahieren

📆 DIMENSION 5 — PLAUSIBILITÄT
- Passt das Datum zum Kontext? (Turnier am Wochentag vs. Wochenende)
- Multi-Tag-Event? (Turnier = oft Sa+So, Urlaub = mehrere Tage)
- Wenn mehrere Daten genannt → pro Tag ein Eintrag
- Zeitraum ("vom 15. bis 18.") → Starttag als Eintrag

💭 DIMENSION 6 — INTENTION
- Ist das WIRKLICH ein Termin, oder nur Smalltalk/Erzählung?
- "Enno hatte gestern Training" → KEIN Termin (Vergangenheit!)
- "Enno hat morgen Training" → Termin (Zukunft)
- "Wollen wir mal wieder essen gehen?" → KEIN Termin (vage Idee)
- "Lass uns Freitag essen gehen" → Termin (konkretes Datum)

═══ KATEGORIEN ═══
- "appointment": Fester Termin mit Datum (Arzt, Treffen, Training, Turnier, Abholen, Geburtstag)
- "reminder": Konkreter Gegenstand mitbringen/kaufen/besorgen
- "task": Aufgabe/Vorbereitung (packen, vorbereiten, organisieren)

═══ UHRZEITEN ═══
- Mit Uhrzeit ("um 15 Uhr", "16:30", "ab 14 Uhr") → "all_day": false, "datetime": "YYYY-MM-DDTHH:MM"
- Ohne Uhrzeit (Geburtstag, Feiertag, Turnier-Tag) → "all_day": true, "datetime": "YYYY-MM-DD"

═══ SMARTE ERINNERUNGEN ═══
- Einkauf: NICHT Sonntag. Trigger: 1-2 Werktage vorher
- Packen/Vorbereiten: Vorabend. Trigger: -PT14H
- Termin: -P1D und -PT2H
- Arzt: -P7D, -P1D, -PT2H
- Turnier/Wettkampf: -P3D, -P1D, -PT2H

{existing_termine}

{feedback_examples}

{memory_context}"""

USER_PROMPT = """Heute ist {today} ({weekday}).

{conversation_context}

═══ AKTUELLE NACHRICHT von {sender} ═══
"{text}"

═══ ANALYSE ═══

Bewerte die Nachricht dimensional:

SCHRITT 1 — DIMENSIONEN (kurz, je 1 Zeile):
📅 Zeit: [Gibt es ein konkretes Datum/Uhrzeit? Welches?]
🏠 Familie: [Wer ist betroffen? Relevanz?]
🎯 Handlung: [Muss jemand etwas TUN?]
🔄 Kontext: [Schon besprochen? Duplikat? Update?]
📆 Plausibilität: [Macht das Datum Sinn?]
💭 Intention: [Echter Termin oder nur Erwähnung/Smalltalk?]

SCHRITT 2 — HYPOTHESEN:
H1: [Es ist ein Termin weil...]
H2: [Es ist KEIN Termin weil...]
H3: [Es ist ein Update/Duplikat weil...] (optional)

SCHRITT 3 — ENTSCHEIDUNG:
Gewählte Hypothese: H[X] weil [Begründung]

SCHRITT 4 — ERGEBNIS:
Wenn H1 gewählt, JSON-Array mit Termin(en).
Wenn H2/H3 gewählt: []

Format pro Termin:
[{{
  "title": "Kurze Beschreibung",
  "datetime": "YYYY-MM-DDTHH:MM oder YYYY-MM-DD",
  "all_day": true/false,
  "participants": ["Name"],
  "confidence": 0.0-1.0,
  "category": "appointment|reminder|task",
  "relevance": "for_me|shared|partner_only|affects_me",
  "reminders": [{{"trigger": "-P1D", "description": "..."}}],
  "reasoning": "Zusammenfassung der Dimensionen-Analyse und Entscheidung"
}}]"""


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

    # LLM cascade: Groq → Gemini
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
        r'\d{1,2}\.\d{1,2}\.',  # 14.02.
        r'\d{1,2}:\d{2}',  # 10:00, 14:30
        r'(montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)',
        r'(morgen|übermorgen|nächste|kommende)',
        r'(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)',
        r'(termin|treffen|arzt|zahnarzt|kinderarzt|meeting|verabredung|training|geburtstag)',
        r'(abholen|hort|schule|kita|wettkampf|turnier|meisterschaft)',
        r'um \d{1,2}\s*(uhr)?',
        r'ab \d{1,2}\s*(uhr)?',
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
        existing_block = f"\nBEREITS EXISTIERENDE TERMINE (NICHT nochmal extrahieren!):\n{existing_termine}"

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
        conv_block = f"KONVERSATIONS-VERLAUF (vorherige Nachrichten, chronologisch):\n{conversation_context}\n"

    user = USER_PROMPT.format(
        today=today,
        weekday=weekday,
        sender=sender,
        text=text,
        conversation_context=conv_block,
    )

    return system, user


def _parse_extraction_response(response_text: str, sender: str) -> list[ExtractedTermin] | None:
    """Parse LLM response — handles reasoning text followed by JSON array.

    The ToT-style prompt produces reasoning steps before the JSON.
    We extract the JSON array from anywhere in the response.
    """
    if not response_text:
        return []

    response_text = response_text.strip()

    # Log the reasoning steps (everything before JSON) for transparency
    json_start = response_text.find("[")
    if json_start > 0:
        reasoning_text = response_text[:json_start].strip()
        if reasoning_text:
            # Log first 500 chars of reasoning for debugging
            logger.debug(f"LLM reasoning: {reasoning_text[:500]}")

    parsed = None

    # 1. Try {"termine": [...]} wrapper
    wrapper_match = re.search(r'\{\s*"termine"\s*:\s*(\[.*?\])\s*\}', response_text, re.DOTALL)
    if wrapper_match:
        try:
            parsed = json.loads(wrapper_match.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Try raw JSON array (handles reasoning text before [])
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
        async with httpx.AsyncClient(timeout=45.0) as client:
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
                    "temperature": 0.2,
                    "max_tokens": 2048,
                },
            )

            if resp.status_code != 200:
                logger.warning(f"Groq termin error: {resp.status_code} {resp.text[:200]}")
                return None

            response_text = resp.json()["choices"][0]["message"]["content"]
            logger.debug(f"Groq raw response: {response_text[:800]}")
            results = _parse_extraction_response(response_text, sender)

            if results is not None:
                for r in results:
                    logger.info(f"Groq: '{r.title}' @ {r.datetime_str} (all_day={r.all_day}, conf={r.confidence}, cat={r.category}, rel={r.relevance}) — {r.reasoning[:300]}")
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
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "contents": [{"parts": [{"text": combined_prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
                },
            )

            if resp.status_code != 200:
                logger.warning(f"Gemini termin error: {resp.status_code}")
                return None

            candidates = resp.json().get("candidates", [])
            if not candidates:
                return []

            response_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            logger.debug(f"Gemini raw response: {response_text[:800]}")
            results = _parse_extraction_response(response_text, sender)

            if results is not None:
                for r in results:
                    logger.info(f"Gemini: '{r.title}' @ {r.datetime_str} (all_day={r.all_day}, conf={r.confidence}, cat={r.category}, rel={r.relevance}) — {r.reasoning[:300]}")
                if not results:
                    logger.info(f"Gemini: no termine in '{text[:60]}...'")
            return results

    except Exception as e:
        logger.warning(f"Gemini termin extraction error: {e}")
        return None
