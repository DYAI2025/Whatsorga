"""RAG Store — ChromaDB integration for semantic message memory.

Embeds messages with all-MiniLM-L6-v2, supports similarity search
for context retrieval (top-20 similar messages).
"""

import logging
from uuid import UUID

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ChromaDB REST API (using the HTTP client directly to avoid heavy dependencies)
COLLECTION_NAME = "messages"


class RAGStore:
    """Thin wrapper around ChromaDB HTTP API."""

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
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/collections/{self._collection_id}/add",
                    json={
                        "ids": [str(message_id)],
                        "documents": [text],
                        "metadatas": [metadata],
                    },
                )
                if resp.status_code not in (200, 201):
                    logger.warning(f"ChromaDB add: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"ChromaDB add error: {e}")

    async def query_similar(self, text: str, n_results: int = 20) -> list[dict]:
        """Find the top-N most similar messages."""
        await self.ensure_collection()
        if not self._collection_id:
            return []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/collections/{self._collection_id}/query",
                    json={
                        "query_texts": [text],
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
