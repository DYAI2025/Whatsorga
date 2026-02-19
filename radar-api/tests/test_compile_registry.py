"""Tests for the registry compiler."""

import json
import tempfile
from pathlib import Path

import yaml


def _make_marker_yaml(tmp: Path, marker_id: str, signals: list[str], patterns: list[str], examples: list[str] | None = None):
    """Write a minimal marker YAML file."""
    data = {
        "id": marker_id,
        "frame": {"signal": signals},
        "pattern": patterns,
        "examples": {"positive": examples or [], "negative": []},
        "tags": ["test"],
    }
    (tmp / f"{marker_id}.yaml").write_text(yaml.dump(data))


def _make_category_mapping(tmp: Path, mapping: dict[str, str]):
    """Write a category mapping YAML."""
    (tmp / "category_mapping.yaml").write_text(yaml.dump(mapping))


def test_compile_produces_valid_registry():
    from scripts.compile_registry import compile_registry

    with tempfile.TemporaryDirectory() as tmpdir:
        markers_dir = Path(tmpdir) / "markers"
        markers_dir.mkdir()
        out_dir = Path(tmpdir) / "out"
        out_dir.mkdir()

        _make_marker_yaml(markers_dir, "ATO_TEST_ANGER", ["Wut", "wütend sein"], [r"(?i)\bwütend\b"])
        _make_marker_yaml(markers_dir, "SEM_TEST_JOY", ["Freude empfinden"], [], ["Ich bin so glücklich heute!"])
        _make_category_mapping(out_dir, {"ATO_TEST_ANGER": "konflikt", "SEM_TEST_JOY": "freude"})

        output_path = out_dir / "registry.json"
        compile_registry(
            markers_dir=str(markers_dir),
            category_mapping_path=str(out_dir / "category_mapping.yaml"),
            output_path=str(output_path),
        )

        assert output_path.exists()
        registry = json.loads(output_path.read_text())

        # Structure checks
        assert registry["embedding_dim"] == 384
        assert "ATO_TEST_ANGER" in registry["category_map"]
        assert registry["category_map"]["ATO_TEST_ANGER"] == "konflikt"
        assert len(registry["markers"]) == 2

        # Each marker has embeddings
        for marker in registry["markers"]:
            assert len(marker["embeddings"]) > 0
            assert len(marker["embeddings"][0]) == 384


def test_compile_skips_markers_without_signals():
    from scripts.compile_registry import compile_registry

    with tempfile.TemporaryDirectory() as tmpdir:
        markers_dir = Path(tmpdir) / "markers"
        markers_dir.mkdir()
        out_dir = Path(tmpdir) / "out"
        out_dir.mkdir()

        # Marker with no frame.signal
        bad = {"id": "ATO_EMPTY", "tags": ["test"]}
        (markers_dir / "ATO_EMPTY.yaml").write_text(yaml.dump(bad))

        _make_marker_yaml(markers_dir, "ATO_GOOD", ["signal text"], [])
        _make_category_mapping(out_dir, {"ATO_GOOD": "stress"})

        output_path = out_dir / "registry.json"
        compile_registry(
            markers_dir=str(markers_dir),
            category_mapping_path=str(out_dir / "category_mapping.yaml"),
            output_path=str(output_path),
        )

        registry = json.loads(output_path.read_text())
        marker_ids = [m["id"] for m in registry["markers"]]
        assert "ATO_GOOD" in marker_ids
        assert "ATO_EMPTY" not in marker_ids
