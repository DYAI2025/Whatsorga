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
from datetime import datetime, timedelta

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
    action: str = "create"  # create | update | cancel
    updates_termin_id: str | None = None  # UUID of existing termin to update/cancel


SYSTEM_PROMPT = """Du bist ein tiefdenkendes Termin-Analyse-System für {user_name}s WhatsApp-Chat mit Partner/in {partner_name}.
Du analysierst NICHT oberflächlich — du denkst in DIMENSIONEN bevor du entscheidest.

═══ FAMILIEN-KONTEXT ═══
{family_context}
- ALLE Kinder-Termine betreffen BEIDE Eltern → "shared"
- "partner_only" NUR für rein persönliche Termine des Partners OHNE Familie

═══ MULTI-DIMENSIONALE ANALYSE ═══

Du MUSST jede Nachricht durch diese 6 Dimensionen bewerten bevor du entscheidest:

📅 DIMENSION 1 — ZEIT
- Enthält die Nachricht ein konkretes Datum oder eine Uhrzeit?
- ACHTUNG: Zahlen im Chat sind NICHT immer Uhrzeiten! "15:46" in einer Nachricht ist oft der Zeitstempel, nicht ein Termin.
- Datum exakt übernehmen: "25.02." → 2026-02-25
- Bei Wochentagen: NICHT selbst rechnen! Nutze die KALENDER-TABELLE unten!
- Bei "morgen", "übermorgen": Relativ zu heute berechnen

{calendar_table}

🏠 DIMENSION 2 — FAMILIE & RELEVANZ
- Betrifft es die Kinder? → "shared" (IMMER, egal wer schreibt)
- Nur Partner/in persönlich (Yoga, Friseur, Freunde)? → "partner_only"
- {user_name} muss etwas vorbereiten/wissen? → "affects_me"
- Beide direkt beteiligt? → "shared"

🎯 DIMENSION 3 — HANDLUNGSBEDARF
- Muss jemand irgendwo HINGEHEN? → "appointment"
- Muss etwas GEKAUFT/MITGEBRACHT werden? → "reminder"
- Muss etwas VORBEREITET/ORGANISIERT werden? → "task"
- Ist es nur INFORMATION ohne Handlung? → vielleicht kein Termin!

🔄 DIMENSION 4 — KONTEXT, DUPLIKATE & UPDATES
- Wurde dasselbe Thema in den vorherigen Nachrichten schon besprochen?
- Existiert der Termin bereits in der DB-Liste? → Prüfe ob UPDATE oder DUPLIKAT:
  • DUPLIKAT: Gleicher Termin, keine neuen Infos → NICHT nochmal extrahieren, leeres Array []
  • UPDATE: Gleicher Termin, ABER neue/geänderte Infos (neue Uhrzeit, Absage, Ort) → action="update" mit updates_termin_id
  • ABSAGE: Termin fällt aus / wird abgesagt → action="cancel" mit updates_termin_id
- Wird das gleiche Event mehrfach erwähnt? → Nur EINMAL extrahieren
- WICHTIG: Bei Updates/Absagen die ID aus der EXISTIERENDE-TERMINE-Liste verwenden!

📆 DIMENSION 5 — PLAUSIBILITÄT
- Passt das Datum zum Kontext? (Turnier am Wochentag vs. Wochenende)
- Multi-Tag-Event? (Turnier = oft Sa+So, Urlaub = mehrere Tage)
- Wenn mehrere Daten genannt → pro Tag ein Eintrag
- Zeitraum ("vom 15. bis 18.") → Starttag als Eintrag

💭 DIMENSION 6 — INTENTION
- Ist das WIRKLICH ein Termin, oder nur Smalltalk/Erzählung?
- "Kind hatte gestern Training" → KEIN Termin (Vergangenheit!)
- "Kind hat morgen Training" → Termin (Zukunft)
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
H1: [Es ist ein NEUER Termin weil...]
H2: [Es ist KEIN Termin weil...]
H3: [Es ist ein UPDATE eines bestehenden Termins weil...]
H4: [Es ist eine ABSAGE eines bestehenden Termins weil...]

SCHRITT 3 — ENTSCHEIDUNG:
Gewählte Hypothese: H[X] weil [Begründung]

SCHRITT 4 — ERGEBNIS:
H1 → action="create", neuer Termin
H2 → leeres Array []
H3 → action="update", updates_termin_id=ID des bestehenden Termins
H4 → action="cancel", updates_termin_id=ID des bestehenden Termins

Format pro Termin:
[{{
  "action": "create|update|cancel",
  "updates_termin_id": "ID aus EXISTIERENDE TERMINE (nur bei update/cancel)",
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
MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
             "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _build_calendar_table(timestamp: datetime) -> str:
    """Build a 3-week calendar lookup table so the LLM never needs to calculate dates.

    This eliminates the #1 source of errors: LLMs can't do weekday arithmetic.
    Instead of 'Mittwoch = ???', the LLM just looks up: Mittwoch = 18.02.2026
    """
    # Find Monday of current week
    monday = timestamp - timedelta(days=timestamp.weekday())

    lines = ["KALENDER-TABELLE (Wochentag → Datum):"]
    for week_offset, label in [(0, "DIESE WOCHE"), (1, "NÄCHSTE WOCHE"), (2, "ÜBERNÄCHSTE WOCHE")]:
        week_start = monday + timedelta(weeks=week_offset)
        days = []
        for d in range(7):
            day = week_start + timedelta(days=d)
            day_name = WEEKDAYS_DE[day.weekday()][:2]  # Mo, Di, Mi, ...
            days.append(f"{day_name} {day.strftime('%d.%m.')}")
        lines.append(f"  {label}: {' | '.join(days)}")

    # Also add "morgen" and "übermorgen" for convenience
    morgen = timestamp + timedelta(days=1)
    ubermorgen = timestamp + timedelta(days=2)
    lines.append(f'  "morgen" = {WEEKDAYS_DE[morgen.weekday()]} {morgen.strftime("%d.%m.%Y")}')
    lines.append(f'  "übermorgen" = {WEEKDAYS_DE[ubermorgen.weekday()]} {ubermorgen.strftime("%d.%m.%Y")}')

    return "\n".join(lines)


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
    user_name = settings.termin_user_name or "User"
    partner_name = settings.termin_partner_name or "Partner"
    children = settings.termin_children_names or ""

    # Build family context from config
    if settings.termin_family_context:
        family_ctx = settings.termin_family_context
    else:
        family_ctx = f"- {user_name} und {partner_name}: Paar"
        if children:
            family_ctx += f" mit Kindern {children}"

    feedback_block = ""
    if feedback_examples:
        feedback_block = f"\nFEEDBACK-BEISPIELE (lerne daraus):\n{feedback_examples}"

    memory_block = ""
    if memory_context:
        memory_block = f"\nKONTEXT AUS GEDÄCHTNIS:\n{memory_context}"

    existing_block = ""
    if existing_termine:
        existing_block = f"\nBEREITS EXISTIERENDE TERMINE (NICHT nochmal extrahieren!):\n{existing_termine}"

    calendar_table = _build_calendar_table(timestamp)

    system = SYSTEM_PROMPT.format(
        user_name=user_name,
        partner_name=partner_name,
        family_context=family_ctx,
        feedback_examples=feedback_block,
        memory_context=memory_block,
        existing_termine=existing_block,
        calendar_table=calendar_table,
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

    # 2. Try to find the JSON result array in the response.
    #    ToT reasoning often contains [...] brackets (markdown, nested arrays)
    #    Strategy: find all top-level [...] candidates, try each from last to first,
    #    accept only if it looks like a termin array (empty or has "title"/"datetime" keys).
    if parsed is None:
        all_starts = [m.start() for m in re.finditer(r'\[', response_text)]
        for start in reversed(all_starts):
            # Try greedy match from this position (captures nested arrays)
            candidate = response_text[start:]
            bracket_match = re.match(r'\[.*\]', candidate, re.DOTALL)
            if not bracket_match:
                continue
            try:
                candidate_parsed = json.loads(bracket_match.group())
                if not isinstance(candidate_parsed, list):
                    continue
                # Accept empty arrays (= no termin found)
                if len(candidate_parsed) == 0:
                    parsed = candidate_parsed
                    break
                # Accept if items look like termine (have title or datetime)
                if isinstance(candidate_parsed[0], dict) and (
                    "title" in candidate_parsed[0] or "datetime" in candidate_parsed[0]
                ):
                    parsed = candidate_parsed
                    break
            except json.JSONDecodeError:
                continue

    if parsed is None:
        # Check if response just says "no termin" without JSON brackets
        # This happens when Gemini responds in natural language without []
        no_termin_hints = [
            "kein termin", "keine termine", "kein relevanter",
            "kein konkretes datum", "kein datum", "kein handlungsbedarf",
            "es ist kein termin", "nicht relevant",
        ]
        response_lower = response_text.lower()
        if any(hint in response_lower for hint in no_termin_hints):
            logger.debug(f"LLM says no termine (no JSON brackets): {response_text[:200]}")
            return []

        logger.warning(f"Failed to parse LLM response (no JSON array found): {response_text[:300]}...")
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
        action = item.get("action", "create")
        if action not in ("create", "update", "cancel"):
            action = "create"
        updates_id = item.get("updates_termin_id")

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
            action=action,
            updates_termin_id=updates_id,
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
                    logger.info(f"Groq: [{r.action}] '{r.title}' @ {r.datetime_str} (all_day={r.all_day}, conf={r.confidence}, cat={r.category}, rel={r.relevance}{f', updates={r.updates_termin_id}' if r.updates_termin_id else ''}) — {r.reasoning[:300]}")
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

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "system_instruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
                },
            )

            if resp.status_code != 200:
                logger.warning(f"Gemini termin error: {resp.status_code} {resp.text[:200]}")
                return None

            candidates = resp.json().get("candidates", [])
            if not candidates:
                return []

            response_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            logger.debug(f"Gemini raw response: {response_text[:800]}")
            results = _parse_extraction_response(response_text, sender)

            if results is None:
                # Gemini responded but we couldn't parse JSON — treat as "no termine"
                # not "LLM unavailable" (which would be misleading)
                logger.info(f"Gemini: unparseable response for '{text[:60]}...': {response_text[:200]}")
                return []

            for r in results:
                logger.info(f"Gemini: [{r.action}] '{r.title}' @ {r.datetime_str} (all_day={r.all_day}, conf={r.confidence}, cat={r.category}, rel={r.relevance}{f', updates={r.updates_termin_id}' if r.updates_termin_id else ''}) — {r.reasoning[:300]}")
            if not results:
                logger.info(f"Gemini: no termine in '{text[:60]}...'")
            return results

    except Exception as e:
        logger.warning(f"Gemini termin extraction error: {e}")
        return None
