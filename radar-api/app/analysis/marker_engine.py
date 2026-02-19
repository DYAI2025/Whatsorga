"""Marker Engine — keyword-based emotional/relational marker detection.

Cherry-picked from Super_semantic_whisper EmotionalAnalyzer + default markers.
Adapted for Beziehungs-Radar: German WhatsApp messages, relationship context.
"""

import re
from dataclasses import dataclass

# Marker categories with German keywords (from SSW + extended for relationship context)
MARKERS: dict[str, list[str]] = {
    # Warmth / closeness
    "waerme": [
        "lieb", "schatz", "vermiss", "kuschel", "drück", "herz",
        "freue mich", "schön", "wunderbar", "danke", "liebevoll",
        "umarmung", "kuss", "süß", "zärtlich", "nah", "geborgen",
    ],
    # Distance / withdrawal
    "distanz": [
        "brauch zeit", "lass mich", "allein", "abstand", "pause",
        "überfordert", "zu viel", "nicht jetzt", "später", "rückzug",
        "brauche raum", "bin müde", "keine lust", "kein bock",
    ],
    # Stress / pressure
    "stress": [
        "stress", "druck", "hektik", "schaff", "überfordert",
        "zu wenig zeit", "deadline", "arbeit", "müde", "erschöpft",
        "nicht geschafft", "muss noch", "krank", "kopfschmerzen",
    ],
    # Conflict / tension
    "konflikt": [
        "streit", "wütend", "sauer", "nerv", "unfair", "ungerecht",
        "enttäuscht", "vorwurf", "schuld", "immer du", "nie",
        "problem", "ärger", "diskussion", "meinungsverschied",
    ],
    # Joy / enthusiasm
    "freude": [
        "super", "toll", "genial", "mega", "geil", "wow",
        "fantastisch", "begeistert", "happy", "freu", "yay",
        "endlich", "geschafft", "perfekt", "feier", "cool",
    ],
    # Sadness / melancholy
    "trauer": [
        "traurig", "weinen", "verloren", "leer", "einsam",
        "vermisse", "schmerz", "schwer", "schlimm", "tut weh",
        "hoffnungslos", "verzweifelt", "hilflos",
    ],
    # Care / concern
    "fuersorge": [
        "wie geht", "alles gut", "pass auf", "gute besserung",
        "sorge", "mach mir sorgen", "gesund", "aufpassen",
        "brauchst du", "kann ich helfen", "bin da", "halt durch",
    ],
    # Planning / future
    "planung": [
        "wollen wir", "am wochenende", "nächste woche", "treffen",
        "plan", "verabreden", "termin", "wann", "datum", "urlaub",
        "zusammen", "gemeinsam", "vorhaben", "lust auf",
    ],
    # Gratitude / appreciation
    "dankbarkeit": [
        "danke", "dankbar", "wertschätze", "bedeutet mir",
        "froh dass", "glücklich", "schätze", "gut dass",
    ],
    # Uncertainty / insecurity
    "unsicherheit": [
        "weiß nicht", "keine ahnung", "vielleicht", "mal sehen",
        "unsicher", "angst", "sorge", "hoffe", "befürchte",
        "bin mir nicht sicher", "kann sein",
    ],
}


@dataclass
class MarkerResult:
    markers: dict[str, float]  # category -> normalized score (0-1)
    dominant: str | None  # highest scoring category
    categories: list[str]  # all matched categories (score > 0)
    raw_counts: dict[str, int]  # category -> raw keyword hit count


def analyze_markers(text: str) -> MarkerResult:
    """Analyze text for emotional/relational markers. Returns scored categories."""
    if not text:
        return MarkerResult(markers={}, dominant=None, categories=[], raw_counts={})

    text_lower = text.lower()
    raw_counts: dict[str, int] = {}

    for category, keywords in MARKERS.items():
        count = 0
        for kw in keywords:
            # Count substring matches
            count += len(re.findall(re.escape(kw), text_lower))
        if count > 0:
            raw_counts[category] = count

    if not raw_counts:
        return MarkerResult(markers={}, dominant=None, categories=[], raw_counts={})

    # Normalize to 0-1 range
    max_count = max(raw_counts.values())
    markers = {cat: count / max_count for cat, count in raw_counts.items()}

    dominant = max(markers, key=markers.get)
    categories = sorted(raw_counts.keys(), key=lambda c: raw_counts[c], reverse=True)

    return MarkerResult(
        markers=markers,
        dominant=dominant,
        categories=categories,
        raw_counts=raw_counts,
    )
