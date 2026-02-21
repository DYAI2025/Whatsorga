"""Person Context — loads per-person YAML profiles for semantic termin extraction.

Each person has a YAML file in data/persons/ with:
- fakten: key biographical facts
- aktivitaeten: recurring activities with termin_logik rules
- termin_hinweise: specific reasoning hints for the LLM

These profiles give the LLM "life experience" about each family member,
enabling it to ask the right questions and make correct inferences.
"""

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Singleton: loaded once at startup, cached
_person_profiles: dict[str, dict] = {}
_loaded = False

PERSONS_DIR = Path(__file__).parent.parent.parent / "data" / "persons"


def reload_persons() -> None:
    """Force reload of person profiles (called after YAML updates)."""
    global _loaded
    _loaded = False
    load_persons()


def load_persons(directory: Path | None = None) -> dict[str, dict]:
    """Load all person YAML files from the persons directory.

    Returns dict mapping lowercase name → full profile.
    Cached after first load.
    """
    global _person_profiles, _loaded

    if _loaded and not directory:
        return _person_profiles

    persons_dir = directory or PERSONS_DIR
    if not persons_dir.exists():
        logger.warning(f"Persons directory not found: {persons_dir}")
        _loaded = True
        return {}

    profiles = {}
    for yaml_file in sorted(persons_dir.glob("*.yaml")):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or "name" not in data:
                continue

            name = data["name"].lower()
            profiles[name] = data

            # Also index by aliases
            for alias in data.get("alias", []):
                profiles[alias.lower()] = data

            logger.info(f"Loaded person profile: {data['name']} ({yaml_file.name})")
        except Exception as e:
            logger.warning(f"Failed to load person profile {yaml_file}: {e}")

    _person_profiles = profiles
    _loaded = True
    logger.info(f"Person context: {len(set(id(p) for p in profiles.values()))} profiles loaded")
    return profiles


def detect_persons(text: str, context: str = "") -> list[dict]:
    """Detect which persons are mentioned in the text or conversation context.

    Returns list of unique person profiles (deduplicated).
    """
    profiles = load_persons()
    if not profiles:
        return []

    combined = f"{text} {context}".lower()
    seen_names = set()
    result = []

    for key, profile in profiles.items():
        if key in combined and profile["name"] not in seen_names:
            seen_names.add(profile["name"])
            result.append(profile)

    return result


def format_person_context(persons: list[dict]) -> str:
    """Format detected person profiles into an LLM-readable context block.

    Structured so the LLM gets:
    1. Who this person is (rolle, fakten)
    2. What activities they do (with termin_logik rules)
    3. Specific reasoning hints for termin extraction
    """
    if not persons:
        return ""

    blocks = []
    for person in persons:
        lines = [f"👤 {person['name']} ({person.get('rolle', '?')})"]

        # Fakten
        fakten = person.get("fakten", [])
        if fakten:
            for f in fakten:
                lines.append(f"  - {f}")

        # Bekannte Orte
        orte = person.get("orte", {})
        if orte:
            lines.append("  📍 Bekannte Orte:")
            for ort_key, ort_data in orte.items():
                name = ort_data.get("name", ort_key)
                kontext = ort_data.get("kontext", "")
                lines.append(f"    • {name}: {kontext}")

        # Aktivitäten mit Termin-Logik
        aktivitaeten = person.get("aktivitaeten", {})
        if aktivitaeten:
            for akt_name, akt in aktivitaeten.items():
                muster = akt.get("muster", "")
                ort = akt.get("ort", "")
                ort_info = f" [Ort: {ort}]" if ort else ""
                lines.append(f"  📌 {akt_name}: {muster}{ort_info}")
                for regel in akt.get("termin_logik", []):
                    lines.append(f"    → {regel}")

        # Termin-Hinweise
        hinweise = person.get("termin_hinweise", [])
        if hinweise:
            lines.append("  ⚡ Termin-Regeln:")
            for h in hinweise:
                lines.append(f"    • {h}")

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def get_person_context(text: str, context: str = "") -> str:
    """One-call function: detect persons and return formatted context block.

    This is the main entry point used by the termin extraction pipeline.
    """
    persons = detect_persons(text, context)
    return format_person_context(persons)
