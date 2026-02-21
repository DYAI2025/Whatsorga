"""Person Learner — auto-enriches person YAML profiles from termin data and feedback.

Learning triggers:
1. After successful termin extraction → detect new activities/patterns
2. After feedback (rejection/edit) → store lesson as termin_hinweis
3. Periodic pattern detection → recurring patterns from DB

No LLM needed — pure pattern matching and DB analysis.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from collections import Counter

import yaml

from app.memory.person_context import PERSONS_DIR, load_persons, reload_persons

logger = logging.getLogger(__name__)


def _read_yaml(person_name: str) -> tuple[dict | None, Path | None]:
    """Read a person's YAML file. Returns (data, path) or (None, None)."""
    yaml_path = PERSONS_DIR / f"{person_name.lower()}.yaml"
    if not yaml_path.exists():
        return None, None
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data, yaml_path
    except Exception as e:
        logger.warning(f"Failed to read {yaml_path}: {e}")
        return None, None


def _write_yaml(data: dict, yaml_path: Path) -> bool:
    """Write updated data back to YAML file."""
    try:
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data, f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=120,
            )
        logger.info(f"Updated person profile: {yaml_path.name}")
        return True
    except Exception as e:
        logger.warning(f"Failed to write {yaml_path}: {e}")
        return False


def _detect_person_in_title(title: str) -> str | None:
    """Detect which person a termin title is about."""
    profiles = load_persons()
    title_lower = title.lower()
    for key, profile in profiles.items():
        if key in title_lower:
            return profile["name"].lower()
    return None


def _normalize_activity(title: str) -> str | None:
    """Extract the core activity from a termin title.

    'Enno Wettkampf bis 18 Uhr' → 'wettkampf'
    'Romy vom Beethoven abholen' → 'abholen'
    'Training' → 'training'
    """
    title_lower = title.lower()
    # Known activity keywords
    activities = [
        "wettkampf", "turnier", "meisterschaft", "schwimmen",
        "training", "abholen", "hort", "schule", "beethoven",
        "geburtstag", "kindergeburtstag", "arzt", "zahnarzt",
        "treffen", "übergabe",
    ]
    for act in activities:
        if act in title_lower:
            return act
    return None


def learn_from_termin(title: str, category: str, relevance: str,
                      confidence: float, all_day: bool,
                      dt: datetime | None = None) -> None:
    """Learn from a successfully extracted termin.

    Called after termin is stored in DB. Checks if there's a new
    activity or pattern worth adding to the person's YAML.
    Fire-and-forget, never raises.
    """
    try:
        person = _detect_person_in_title(title)
        if not person:
            return

        data, yaml_path = _read_yaml(person)
        if not data or not yaml_path:
            return

        activity = _normalize_activity(title)
        if not activity:
            return

        # Check if this activity is already known
        aktivitaeten = data.get("aktivitaeten", {})
        known_activities = set()
        for akt_data in aktivitaeten.values():
            # Collect all words from existing activity descriptions
            muster = str(akt_data.get("muster", "")).lower()
            typ = str(akt_data.get("typ", "")).lower()
            known_activities.update(muster.split())
            known_activities.update(typ.split())

        # Also check activity keys
        known_keys = set(aktivitaeten.keys())

        if activity in known_keys or activity in known_activities:
            # Already known, maybe update time pattern
            if dt and not all_day:
                _maybe_update_time_pattern(data, yaml_path, person, activity, dt)
            return

        # New activity detected — add it
        new_entry = {
            "typ": category,
            "muster": f"Erkannt am {datetime.now().strftime('%d.%m.%Y')}",
            "termin_logik": [f"Auto-gelernt aus: '{title}'"],
        }

        if "aktivitaeten" not in data:
            data["aktivitaeten"] = {}
        data["aktivitaeten"][activity] = new_entry

        _write_yaml(data, yaml_path)
        reload_persons()  # Invalidate cache so next extraction uses updated profile
        logger.info(f"Learned new activity for {person}: {activity} (from '{title}')")

    except Exception as e:
        logger.debug(f"learn_from_termin error (non-fatal): {e}")


def _maybe_update_time_pattern(data: dict, yaml_path: Path,
                                person: str, activity: str,
                                dt: datetime) -> None:
    """Track time patterns for recurring activities.

    Stores observed times in a _learned section. When enough data points
    accumulate, generates a pattern hint.
    """
    learned = data.setdefault("_learned", {})
    time_obs = learned.setdefault("time_observations", {})
    obs_list = time_obs.setdefault(activity, [])

    weekday = dt.strftime("%A")  # Monday, Tuesday, ...
    time_str = dt.strftime("%H:%M")
    entry = f"{weekday} {time_str}"

    # Don't duplicate
    if entry not in obs_list:
        obs_list.append(entry)
        # Keep last 20 observations
        if len(obs_list) > 20:
            obs_list[:] = obs_list[-20:]

        # Check for recurring pattern (3+ same weekday)
        weekday_counts = Counter(e.split()[0] for e in obs_list)
        for day, count in weekday_counts.items():
            if count >= 3:
                # Extract most common time for this day
                day_times = [e.split()[1] for e in obs_list if e.startswith(day)]
                common_time = Counter(day_times).most_common(1)[0][0]
                pattern = f"{activity} ist regelmäßig {day}s um {common_time}"

                # Add to termin_hinweise if not already there
                hinweise = data.setdefault("termin_hinweise", [])
                if not any(pattern.lower() in h.lower() for h in hinweise):
                    hinweise.append(f"[Auto] {pattern}")
                    logger.info(f"Detected recurring pattern for {person}: {pattern}")

        _write_yaml(data, yaml_path)


def learn_from_feedback(title: str, action: str,
                        reason: str | None = None,
                        correction: dict | None = None) -> None:
    """Learn from user feedback on a termin.

    - rejected: Add the rejection reason as a negative rule
    - edited: Add the correction as a pattern hint

    Called from the feedback endpoint. Fire-and-forget, never raises.
    """
    try:
        person = _detect_person_in_title(title)
        if not person:
            return

        data, yaml_path = _read_yaml(person)
        if not data or not yaml_path:
            return

        hinweise = data.setdefault("termin_hinweise", [])

        if action == "rejected" and reason:
            hint = f"[Feedback] '{title}' wurde ABGELEHNT: {reason}"
            if hint not in hinweise:
                hinweise.append(hint)
                _write_yaml(data, yaml_path)
                reload_persons()
                logger.info(f"Learned from rejection for {person}: {reason}")

        elif action == "edited" and correction:
            changes = ", ".join(f"{k}→{v}" for k, v in correction.items())
            hint = f"[Feedback] '{title}' wurde KORRIGIERT: {changes}"
            if hint not in hinweise:
                hinweise.append(hint)
                _write_yaml(data, yaml_path)
                reload_persons()
                logger.info(f"Learned from edit for {person}: {changes}")

    except Exception as e:
        logger.debug(f"learn_from_feedback error (non-fatal): {e}")


async def detect_recurring_patterns(termine_data: list[dict]) -> list[str]:
    """Analyze a list of termine to detect recurring patterns.

    Called periodically or on-demand. Takes raw termin dicts from DB.
    Returns list of detected patterns (for logging/display).

    termine_data format: [{"title": "...", "datetime": dt, "category": "...", "person": "..."}]
    """
    detected = []

    # Group by person + activity
    by_person_activity: dict[tuple[str, str], list[datetime]] = {}
    for t in termine_data:
        person = _detect_person_in_title(t.get("title", ""))
        activity = _normalize_activity(t.get("title", ""))
        if person and activity:
            key = (person, activity)
            dt = t.get("datetime")
            if dt:
                by_person_activity.setdefault(key, []).append(dt)

    for (person, activity), dates in by_person_activity.items():
        if len(dates) < 3:
            continue

        # Check weekday pattern
        weekdays = [d.strftime("%A") for d in dates]
        wday_counts = Counter(weekdays)
        most_common_day, count = wday_counts.most_common(1)[0]

        if count >= 3:
            times = [d.strftime("%H:%M") for d in dates if d.strftime("%A") == most_common_day]
            if times:
                common_time = Counter(times).most_common(1)[0][0]
                pattern = f"{person}/{activity}: regelmäßig {most_common_day}s um {common_time}"
                detected.append(pattern)

                # Write to YAML
                data, yaml_path = _read_yaml(person)
                if data and yaml_path:
                    hinweise = data.setdefault("termin_hinweise", [])
                    pattern_hint = f"[Auto] {activity} ist regelmäßig {most_common_day}s um {common_time}"
                    if not any(pattern_hint.lower() in h.lower() for h in hinweise):
                        hinweise.append(pattern_hint)
                        _write_yaml(data, yaml_path)

    return detected
