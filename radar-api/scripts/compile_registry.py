"""Compile YAML markers into marker_registry_radar.json with pre-computed embeddings.

Usage:
    python -m scripts.compile_registry \
        --markers-dir ../../Marker/WTME_ALL_Marker-LD3.4.1-5.1 \
        --category-mapping data/category_mapping.yaml \
        --output data/marker_registry_radar.json
"""

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
DEFAULT_THRESHOLD = 0.65


def _load_embedding_model():
    from sentence_transformers import SentenceTransformer
    logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}")
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def _parse_marker(path: Path) -> dict | None:
    """Parse a YAML marker file. Returns None if unusable."""
    try:
        data = yaml.safe_load(path.read_text())
    except Exception as e:
        logger.warning(f"Failed to parse {path.name}: {e}")
        return None

    if not isinstance(data, dict) or "id" not in data:
        return None

    marker_id = data["id"]
    frame = data.get("frame", {}) or {}
    signals = frame.get("signal", []) or []
    patterns = data.get("pattern", []) or []
    examples_block = data.get("examples", {}) or {}
    if isinstance(examples_block, list):
        # Some markers store examples as a flat list (treat as positive)
        positive_examples = examples_block
    else:
        positive_examples = examples_block.get("positive", []) or []

    # Collect all texts to embed: signals + positive examples
    texts_to_embed = []
    for s in signals:
        if isinstance(s, str) and len(s.strip()) > 1:
            texts_to_embed.append(s.strip())
    for ex in positive_examples:
        if isinstance(ex, str) and len(ex.strip()) > 3:
            texts_to_embed.append(ex.strip())

    if not texts_to_embed and not patterns:
        logger.info(f"Skipping {marker_id}: no signals, examples, or patterns")
        return None

    # Determine layer from ID prefix
    layer = "UNK"
    for prefix in ("ATO", "SEM", "CLU", "MEMA"):
        if marker_id.startswith(prefix):
            layer = prefix
            break

    return {
        "id": marker_id,
        "layer": layer,
        "patterns": patterns,
        "signals": [s.strip() for s in signals if isinstance(s, str)],
        "texts_to_embed": texts_to_embed,
        "threshold": DEFAULT_THRESHOLD,
        "tags": data.get("tags", []),
    }


def compile_registry(
    markers_dir: str,
    category_mapping_path: str,
    output_path: str,
):
    """Main compile function."""
    markers_path = Path(markers_dir)
    cat_map_path = Path(category_mapping_path)
    out_path = Path(output_path)

    # Load category mapping
    category_map = {}
    if cat_map_path.exists():
        raw = yaml.safe_load(cat_map_path.read_text()) or {}
        category_map = {k: v for k, v in raw.items() if isinstance(v, str)}
        logger.info(f"Loaded category mapping: {len(category_map)} entries")

    # Parse all YAML markers
    yaml_files = sorted(markers_path.glob("*.yaml"))
    parsed = []
    for yf in yaml_files:
        marker = _parse_marker(yf)
        if marker:
            parsed.append(marker)

    logger.info(f"Parsed {len(parsed)} markers from {len(yaml_files)} YAML files")

    # Collect all texts to embed
    all_texts = []
    text_to_marker_idx = []  # maps text index -> parsed marker index
    for i, marker in enumerate(parsed):
        for text in marker["texts_to_embed"]:
            all_texts.append(text)
            text_to_marker_idx.append(i)

    # Compute embeddings
    if all_texts:
        model = _load_embedding_model()
        logger.info(f"Embedding {len(all_texts)} texts...")
        embeddings = model.encode(all_texts, normalize_embeddings=True, show_progress_bar=False)
        logger.info(f"Embeddings computed: shape {embeddings.shape}")
    else:
        embeddings = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

    # Build mapping from marker index to its embeddings in a single pass
    marker_idx_to_embeddings = {i: [] for i in range(len(parsed))}
    for j, midx in enumerate(text_to_marker_idx):
        # Each entry in text_to_marker_idx corresponds to embeddings[j]
        marker_idx_to_embeddings[midx].append(embeddings[j].tolist())

    # Build registry markers with embeddings
    registry_markers = []
    for i, marker in enumerate(parsed):
        marker_embeddings = marker_idx_to_embeddings.get(i, [])

        registry_markers.append({
            "id": marker["id"],
            "layer": marker["layer"],
            "patterns": marker["patterns"],
            "signals": marker["signals"],
            "embeddings": marker_embeddings,
            "threshold": marker["threshold"],
            "tags": marker["tags"],
        })

    # Build final registry
    registry = {
        "version": "5.1",
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": EMBEDDING_MODEL_NAME,
        "embedding_dim": EMBEDDING_DIM,
        "category_map": {m["id"]: category_map.get(m["id"], "") for m in registry_markers},
        "markers": registry_markers,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(registry, ensure_ascii=False, indent=None))
    logger.info(f"Registry written to {out_path} ({len(registry_markers)} markers, {len(all_texts)} embeddings)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compile YAML markers into radar registry JSON")
    parser.add_argument("--markers-dir", required=True, help="Path to YAML marker directory")
    parser.add_argument("--category-mapping", required=True, help="Path to category_mapping.yaml")
    parser.add_argument("--output", required=True, help="Output path for registry JSON")
    args = parser.parse_args()

    compile_registry(
        markers_dir=args.markers_dir,
        category_mapping_path=args.category_mapping,
        output_path=args.output,
    )
