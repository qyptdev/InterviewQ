"""Embedding API wrapper."""

import logging
import os
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _check_memory_limit(limit_mb: int = 1024) -> bool:
    """Check if current process RSS is below limit_mb. Returns False if over."""
    try:
        import psutil
        rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        if rss_mb > limit_mb:
            logger.warning(f"Memory limit check: RSS={rss_mb:.0f}MB > {limit_mb}MB, skipping embedding")
            return False
    except ImportError:
        # psutil not available, skip check
        pass
    return True


class EmbeddingClient:
    """Client for embedding API."""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.llm_embedding_base_url
        self.api_key = settings.llm_embedding_api_key
        self.model = settings.llm_embedding_model
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(
                    connect=get_settings().llm_connect_timeout,
                    read=get_settings().llm_read_timeout,
                    write=get_settings().llm_write_timeout,
                    pool=get_settings().llm_pool_timeout,
                ),
            )
        return self._client

    async def close(self) -> None:
        """Close the httpx client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for a list of texts."""
        if not _check_memory_limit():
            raise RuntimeError("Memory limit exceeded, skipping embedding")

        client = await self._get_client()

        try:
            response = await client.post(
                "/embeddings",
                json={
                    "model": self.model,
                    "input": texts,
                },
            )
            response.raise_for_status()
            data = response.json()

            # Extract embeddings in order
            embeddings = []
            for item in sorted(data["data"], key=lambda x: x["index"]):
                embeddings.append(item["embedding"])

            return embeddings
        except Exception as e:
            logger.error(f"Embedding API error: {e}")
            raise

    async def embed_single(self, text: str) -> list[float]:
        """Get embedding for a single text."""
        embeddings = await self.embed([text])
        return embeddings[0] if embeddings else []


# Global embedding client
_embedding_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> Optional["EmbeddingClient"]:
    """Get the global embedding client, or None if embedding is disabled."""
    global _embedding_client
    settings = get_settings()
    if not settings.embedding_enabled:
        logger.info("Embedding disabled via EMBEDDING_ENABLED=false")
        return None
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client
