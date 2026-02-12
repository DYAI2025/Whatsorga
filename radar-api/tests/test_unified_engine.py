"""Tests for the unified marker engine."""

import json
import tempfile
from pathlib import Path

import numpy as np


def _make_test_registry(path: Path, markers: list[dict] | None = None, category_map: dict | None = None):
    """Write a minimal test registry JSON."""
    if markers is None:
        markers = [
            {
                "id": "ATO_TEST_ANGER",
                "layer": "ATO",
                "patterns": [r"(?i)\bwütend\b", r"(?i)\bsauer\b"],
                "signals": ["Wut", "wütend sein"],
                "embeddings": [np.random.randn(384).tolist()],
                "threshold": 0.65,
                "tags": ["test"],
            },
            {
                "id": "SEM_TEST_JOY",
                "layer": "SEM",
                "patterns": [],
                "signals": ["Freude empfinden"],
                "embeddings": [np.random.randn(384).tolist()],
                "threshold": 0.65,
                "tags": ["test"],
            },
        ]
    if category_map is None:
        category_map = {"ATO_TEST_ANGER": "konflikt", "SEM_TEST_JOY": "freude"}

    registry = {
        "version": "test",
        "compiled_at": "2026-01-01T00:00:00Z",
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_dim": 384,
        "category_map": category_map,
        "markers": markers,
    }
    path.write_text(json.dumps(registry))


def test_engine_loads_registry():
    from app.analysis.unified_engine import UnifiedMarkerEngine

    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "registry.json"
        _make_test_registry(reg_path)

        engine = UnifiedMarkerEngine()
        engine.load(registry_path=str(reg_path), skip_model=True)

        assert engine._loaded is True
        assert len(engine._patterns) == 2
        assert "ATO_TEST_ANGER" in engine._patterns


def test_engine_fallback_when_registry_missing():
    from app.analysis.unified_engine import UnifiedMarkerEngine

    engine = UnifiedMarkerEngine()
    engine.load(registry_path="/nonexistent/path.json", skip_model=True)

    assert engine._loaded is False

    # Should still produce results via legacy fallback
    result = engine.analyze("Ich bin total wütend und sauer auf dich")
    assert result.dominant is not None  # legacy engine found "konflikt"
    assert isinstance(result.raw_counts, dict)


def test_engine_regex_phase1_activation():
    from app.analysis.unified_engine import UnifiedMarkerEngine

    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "registry.json"
        _make_test_registry(reg_path)

        engine = UnifiedMarkerEngine()
        engine.load(registry_path=str(reg_path), skip_model=True)

        result = engine.analyze("Ich bin wütend und sauer")
        # ATO_TEST_ANGER should activate via regex
        activated_ids = [m["id"] for m in result.activated_markers]
        assert "ATO_TEST_ANGER" in activated_ids
        # Category aggregation
        assert "konflikt" in result.categories


def test_engine_empty_text():
    from app.analysis.unified_engine import UnifiedMarkerEngine

    engine = UnifiedMarkerEngine()
    engine.load(registry_path="/nonexistent/path.json", skip_model=True)

    result = engine.analyze("")
    assert result.dominant is None
    assert result.markers == {}
    assert result.activated_markers == []


def test_result_backward_compatible_shape():
    from app.analysis.unified_engine import UnifiedMarkerEngine

    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "registry.json"
        _make_test_registry(reg_path)

        engine = UnifiedMarkerEngine()
        engine.load(registry_path=str(reg_path), skip_model=True)

        result = engine.analyze("Ich bin wütend")

        # Must have all legacy fields
        assert hasattr(result, "markers")
        assert hasattr(result, "dominant")
        assert hasattr(result, "categories")
        assert hasattr(result, "raw_counts")
        assert hasattr(result, "activated_markers")

        assert isinstance(result.markers, dict)
        assert isinstance(result.categories, list)
        assert isinstance(result.raw_counts, dict)
        assert isinstance(result.activated_markers, list)

        # markers values are 0-1 floats
        for v in result.markers.values():
            assert 0.0 <= v <= 1.0


import pytest


@pytest.mark.slow
def test_engine_embedding_phase2_activation():
    """Test that embedding similarity activates markers for semantic matches.

    This test loads the real sentence-transformer model (~90MB).
    Skip with: pytest -m 'not slow'
    """
    from app.analysis.unified_engine import UnifiedMarkerEngine
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")

    # Create a marker with an embedding for "Ich habe Angst und bin unsicher"
    anchor_text = "Ich habe Angst und bin unsicher"
    anchor_emb = model.encode(anchor_text, normalize_embeddings=True).tolist()

    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "registry.json"
        markers = [
            {
                "id": "ATO_TEST_FEAR",
                "layer": "ATO",
                "patterns": [],  # No regex — must activate via embedding only
                "signals": ["Angst"],
                "embeddings": [anchor_emb],
                "threshold": 0.55,
                "tags": ["test"],
            },
        ]
        _make_test_registry(reg_path, markers=markers, category_map={"ATO_TEST_FEAR": "unsicherheit"})

        engine = UnifiedMarkerEngine()
        engine.load(registry_path=str(reg_path), skip_model=False)

        # This text is semantically similar but uses different words
        # (cosine similarity ~0.60 with "Ich habe Angst und bin unsicher")
        result = engine.analyze("Ich habe so viel Angst vor der Zukunft")

        activated_ids = [m["id"] for m in result.activated_markers]
        assert "ATO_TEST_FEAR" in activated_ids

        # Verify method is embedding
        fear_activation = next(m for m in result.activated_markers if m["id"] == "ATO_TEST_FEAR")
        assert fear_activation["method"] == "embedding"

        # Category should be mapped
        assert "unsicherheit" in result.categories
