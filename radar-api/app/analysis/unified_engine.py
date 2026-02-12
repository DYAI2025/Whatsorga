"""Unified Marker Engine — loads compiled YAML marker registry, detects via regex + embeddings.

Two-phase detection:
  Phase 1 (regex): Compiled regex patterns from YAML markers. Fast, deterministic.
  Phase 2 (embedding): Cosine similarity against pre-computed marker embeddings. Semantic.

Falls back to legacy marker_engine.py if the registry is missing or broken.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.analysis.marker_engine import analyze_markers as _legacy_analyze
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class MarkerResult:
    markers: dict[str, float]  # category -> normalized score (0-1)
    dominant: str | None  # highest scoring category
    categories: list[str]  # all matched categories (score > 0)
    raw_counts: dict[str, int]  # category -> raw hit count
    activated_markers: list[dict] = field(default_factory=list)


class UnifiedMarkerEngine:
    def __init__(self):
        self._registry: dict | None = None
        self._category_map: dict[str, str] = {}
        self._patterns: dict[str, list[re.Pattern]] = {}  # marker_id -> compiled regexes
        self._embeddings_matrix: np.ndarray | None = None  # shape [N, 384]
        self._embedding_to_marker: list[str] = []  # row index -> marker_id
        self._thresholds: dict[str, float] = {}  # marker_id -> threshold
        self._model = None
        self._loaded = False
        self._embedding_available = False

    def load(self, registry_path: str | None = None, skip_model: bool = False):
        """Load the compiled marker registry. Call once at startup."""
        path = Path(registry_path or settings.marker_registry_path)

        if not path.exists():
            logger.warning(f"Marker registry not found at {path}, using legacy fallback")
            return

        try:
            with open(path) as f:
                self._registry = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load marker registry: {e}")
            return

        self._category_map = self._registry.get("category_map", {})

        # Build compiled regex patterns per marker
        for marker in self._registry.get("markers", []):
            mid = marker["id"]
            compiled = []
            for p in marker.get("patterns", []):
                try:
                    compiled.append(re.compile(p))
                except re.error as e:
                    logger.warning(f"Invalid regex for {mid}: {p} ({e})")
            self._patterns[mid] = compiled
            self._thresholds[mid] = marker.get("threshold", 0.65)

        # Build embedding matrix
        all_embeddings = []
        self._embedding_to_marker = []
        for marker in self._registry.get("markers", []):
            mid = marker["id"]
            for emb in marker.get("embeddings", []):
                all_embeddings.append(emb)
                self._embedding_to_marker.append(mid)

        if all_embeddings:
            self._embeddings_matrix = np.array(all_embeddings, dtype=np.float32)
            norms = np.linalg.norm(self._embeddings_matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self._embeddings_matrix = self._embeddings_matrix / norms

        # Load sentence-transformer model (Phase 2)
        if not skip_model:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer("all-MiniLM-L6-v2")
                self._embedding_available = True
                logger.info("Sentence-transformer model loaded for embedding matching")
            except Exception as e:
                logger.warning(f"Could not load sentence-transformer model: {e}. Embedding matching disabled.")

        self._loaded = True
        logger.info(
            f"Unified marker engine loaded: {len(self._patterns)} markers, "
            f"{len(self._embedding_to_marker)} embeddings, "
            f"embedding_phase={'on' if self._embedding_available else 'off'}"
        )

    def analyze(self, text: str) -> MarkerResult:
        """Analyze text for markers. Returns backward-compatible MarkerResult."""
        if not text:
            return MarkerResult(markers={}, dominant=None, categories=[], raw_counts={})

        if not self._loaded:
            legacy = _legacy_analyze(text)
            return MarkerResult(
                markers=legacy.markers,
                dominant=legacy.dominant,
                categories=legacy.categories,
                raw_counts=legacy.raw_counts,
            )

        activated: dict[str, dict] = {}  # marker_id -> {score, method}

        # Phase 1: Regex matching
        for mid, patterns in self._patterns.items():
            hits = 0
            for pat in patterns:
                hits += len(pat.findall(text))
            if hits > 0:
                activated[mid] = {"score": min(1.0, hits * 0.3), "method": "regex", "hits": hits}

        # Phase 2: Embedding similarity
        if self._embedding_available and self._embeddings_matrix is not None:
            try:
                msg_embedding = self._model.encode(text, normalize_embeddings=True)
                similarities = self._embeddings_matrix @ msg_embedding

                # Per-marker best similarity
                marker_best: dict[str, float] = {}
                for idx, sim in enumerate(similarities):
                    mid = self._embedding_to_marker[idx]
                    if mid not in marker_best or sim > marker_best[mid]:
                        marker_best[mid] = float(sim)

                for mid, best_sim in marker_best.items():
                    threshold = self._thresholds.get(mid, 0.65)
                    if best_sim >= threshold:
                        if mid not in activated or best_sim > activated[mid]["score"]:
                            activated[mid] = {"score": best_sim, "method": "embedding"}
            except Exception as e:
                logger.warning(f"Embedding matching failed (non-fatal): {e}")

        # Aggregate to dashboard categories
        category_scores: dict[str, float] = {}
        category_counts: dict[str, int] = {}
        activated_list = []

        for mid, info in activated.items():
            category = self._category_map.get(mid)
            if category:
                category_scores[category] = category_scores.get(category, 0) + info["score"]
                category_counts[category] = category_counts.get(category, 0) + 1

            activated_list.append({
                "id": mid,
                "layer": mid.split("_")[0] if "_" in mid else "UNK",
                "score": round(info["score"], 3),
                "method": info["method"],
            })

        if not category_scores:
            return MarkerResult(markers={}, dominant=None, categories=[], raw_counts={}, activated_markers=activated_list)

        # Normalize to 0-1
        max_score = max(category_scores.values())
        markers = {cat: round(score / max_score, 3) for cat, score in category_scores.items()}

        dominant = max(markers, key=markers.get)
        categories = sorted(category_scores.keys(), key=lambda c: category_scores[c], reverse=True)

        return MarkerResult(
            markers=markers,
            dominant=dominant,
            categories=categories,
            raw_counts=category_counts,
            activated_markers=activated_list,
        )


# Singleton — call engine.load() at startup
engine = UnifiedMarkerEngine()
