"""RAG Store — ChromaDB integration for semantic message memory.

Uses Groq API (OpenAI-compatible) to compute embeddings, then stores/queries
in ChromaDB via direct HTTP API.
"""

import logging
from uuid import UUID

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "messages"

# Groq doesn't offer embeddings yet, so we use a lightweight local approach:
# Store documents in ChromaDB and use its built-in embedding at query time.
# Since ChromaDB 0.5.x REST API requires client-side embeddings,
# we use a simple TF-IDF-like hash embedding as a fallback.
# For production, switch to a proper embedding API.

EMBED_DIM = 384  # same as all-MiniLM-L6-v2


def _simple_embed(text: str) -> list[float]:
    """Simple deterministic text embedding using character-level hashing.

    Not great for semantics, but sufficient for basic similarity until
    a proper embedding API is configured. Each dimension is a hash
    of overlapping character trigrams, normalized to [-1, 1].
    """
    vec = [0.0] * EMBED_DIM
    text = text.lower().strip()
    if not text:
        return vec

    for i in range(len(text) - 2):
        trigram = text[i:i+3]
        h = hash(trigram) % EMBED_DIM
        vec[h] += 1.0

    # Normalize
    magnitude = sum(v * v for v in vec) ** 0.5
    if magnitude > 0:
        vec = [v / magnitude for v in vec]

    return vec


class RAGStore:
    """Thin wrapper around ChromaDB HTTP API with client-side embeddings."""

    def __init__(self):
        self.base_url = settings.chromadb_url
        self._collection_id: str | None = None

    async def ensure_collection(self):
        """Create or get the messages collection."""
        if self._collection_id:
            return

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try to get existing collection
            try:
                resp = await client.get(
                    f"{self.base_url}/api/v1/collections/{COLLECTION_NAME}"
                )
                if resp.status_code == 200:
                    self._collection_id = resp.json()["id"]
                    return
            except Exception:
                pass

            # Create collection
            try:
                resp = await client.post(
                    f"{self.base_url}/api/v1/collections",
                    json={
                        "name": COLLECTION_NAME,
                        "metadata": {"hnsw:space": "cosine"},
                    },
                )
                if resp.status_code == 200:
                    self._collection_id = resp.json()["id"]
                    logger.info(f"Created ChromaDB collection '{COLLECTION_NAME}'")
                else:
                    logger.warning(f"ChromaDB create collection: {resp.status_code}")
            except Exception as e:
                logger.warning(f"ChromaDB unavailable: {e}")

    async def add_message(
        self,
        message_id: UUID,
        text: str,
        metadata: dict,
    ):
        """Add a message embedding to the collection."""
        await self.ensure_collection()
        if not self._collection_id:
            return

        try:
            embedding = _simple_embed(text)
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/collections/{self._collection_id}/add",
                    json={
                        "ids": [str(message_id)],
                        "documents": [text],
                        "embeddings": [embedding],
                        "metadatas": [metadata],
                    },
                )
                if resp.status_code not in (200, 201):
                    logger.warning(f"ChromaDB add: {resp.status_code} {resp.text[:200]}")
                else:
                    logger.info(f"ChromaDB: embedded message {str(message_id)[:8]}...")
        except Exception as e:
            logger.warning(f"ChromaDB add error: {e}")

    async def query_similar(self, text: str, n_results: int = 20) -> list[dict]:
        """Find the top-N most similar messages."""
        await self.ensure_collection()
        if not self._collection_id:
            return []

        try:
            embedding = _simple_embed(text)
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/collections/{self._collection_id}/query",
                    json={
                        "query_embeddings": [embedding],
                        "n_results": min(n_results, 10),
                        "include": ["documents", "metadatas", "distances"],
                    },
                )
                if resp.status_code not in (200, 201):
                    logger.warning(f"ChromaDB query: {resp.status_code} {resp.text[:300]}")
                    return []

                data = resp.json()
                results = []
                ids = data.get("ids", [[]])[0]
                docs = data.get("documents", [[]])[0]
                metas = data.get("metadatas", [[]])[0]
                dists = data.get("distances", [[]])[0]

                for i in range(len(ids)):
                    results.append({
                        "id": ids[i],
                        "text": docs[i],
                        "metadata": metas[i] if i < len(metas) else {},
                        "distance": dists[i] if i < len(dists) else 1.0,
                    })
                return results

        except Exception as e:
            logger.warning(f"ChromaDB query error: {e}")
            return []


# Singleton
rag_store = RAGStore()
