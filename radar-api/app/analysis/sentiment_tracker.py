"""Sentiment Tracker — scores messages and tracks rolling sentiment per chat.

Uses keyword-based valence scoring (no external LLM needed).
Maintains rolling average for drift detection.
"""

import re
from dataclasses import dataclass

# Positive / negative word lists (German, relationship context)
_POSITIVE = [
    "lieb", "schön", "toll", "super", "danke", "freue", "glücklich",
    "wunderbar", "genial", "perfekt", "gut", "prima", "klasse", "cool",
    "lachen", "spaß", "lustig", "happy", "herzlich", "nett", "süß",
    "fantastisch", "begeistert", "dankbar", "stolz", "froh", "warm",
    "geborgen", "vertraut", "harmonisch", "friedlich", "entspannt",
    "zufrieden", "hoffnung", "positiv", "liebe", "kuss", "herz",
]

_NEGATIVE = [
    "traurig", "wütend", "sauer", "nerv", "stress", "schlecht",
    "schlimm", "problem", "streit", "angst", "sorge", "enttäuscht",
    "einsam", "leer", "müde", "erschöpft", "krank", "schmerz",
    "unfair", "schuld", "vorwurf", "ärger", "frust", "verzweifelt",
    "hilflos", "hoffnungslos", "aggressiv", "wut", "hass", "verletzt",
    "kaputt", "zerbrochen", "weinen", "allein", "überfordert",
]

# Intensifiers and diminishers
_INTENSIFIERS = ["sehr", "extrem", "total", "mega", "voll", "so", "echt", "richtig"]
_NEGATORS = ["nicht", "kein", "keine", "keinen", "nie", "niemals", "kaum"]


@dataclass
class SentimentResult:
    score: float  # -1.0 to +1.0
    positive_hits: int
    negative_hits: int
    label: str  # "positive", "negative", "neutral"


def score_sentiment(text: str) -> SentimentResult:
    """Score sentiment of a text. Returns -1.0 (very negative) to +1.0 (very positive)."""
    if not text:
        return SentimentResult(score=0.0, positive_hits=0, negative_hits=0, label="neutral")

    text_lower = text.lower()
    words = re.findall(r'\b\w+\b', text_lower)

    pos_count = 0
    neg_count = 0

    for i, word in enumerate(words):
        # Check for negation in previous 2 words
        negated = any(words[max(0, i-2):i].__contains__(neg) for neg in _NEGATORS)

        is_pos = any(pw in word for pw in _POSITIVE)
        is_neg = any(nw in word for nw in _NEGATIVE)

        # Check for intensifier in previous word
        intensified = i > 0 and words[i-1] in _INTENSIFIERS
        multiplier = 1.5 if intensified else 1.0

        if is_pos:
            if negated:
                neg_count += multiplier
            else:
                pos_count += multiplier
        elif is_neg:
            if negated:
                pos_count += multiplier * 0.5  # negated negative is weakly positive
            else:
                neg_count += multiplier

    total = pos_count + neg_count
    if total == 0:
        return SentimentResult(score=0.0, positive_hits=0, negative_hits=0, label="neutral")

    score = (pos_count - neg_count) / total  # -1.0 to +1.0

    label = "neutral"
    if score > 0.15:
        label = "positive"
    elif score < -0.15:
        label = "negative"

    return SentimentResult(
        score=round(score, 3),
        positive_hits=int(pos_count),
        negative_hits=int(neg_count),
        label=label,
    )
