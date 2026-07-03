"""Embedding API wrapper with memory-safe streaming response handling.

Memory-safety fixes:
- Uses streaming response to read embedding results incrementally,
  preventing unbounded memory growth with slow/hanging embedding APIs.
- Caps per-request timeout and enforces overall deadline.
- Falls back to single-text embedding on batch timeout.
"""

import logging
import asyncio
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Safety limits for embedding calls
_EMBED_PER_TEXT_TIMEOUT = 15.0   # seconds per text item
_EMBED_MAX_OVERALL = 60.0        # absolute max for any embed call
_EMBED_MAX_BATCH_SIZE = 5         # max texts per single API call


class EmbeddingClient:
    """Client for embedding API with memory-safe response handling."""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.llm_embedding_base_url
        self.api_key = settings.llm_embedding_api_key
        self.model = settings.llm_embedding_model
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx client with pool limits."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=_EMBED_PER_TEXT_TIMEOUT,
                    write=10.0,
                    pool=30.0,
                ),
                limits=httpx.Limits(
                    max_connections=4,
                    max_keepalive_connections=2,
                    keepalive_expiry=15.0,
                ),
            )
        return self._client

    async def close(self) -> None:
        """Close the httpx client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for a list of texts, with memory-safe handling.

        Strategy:
        1. Split into small batches (max _EMBED_MAX_BATCH_SIZE per call)
        2. Use streaming response to avoid buffering entire response
        3. Fall back to single-text embedding on batch failure
        4. Overall deadline prevents hanging forever
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        overall_deadline = asyncio.get_event_loop().time() + _EMBED_MAX_OVERALL

        # Process in small batches
        for i in range(0, len(texts), _EMBED_MAX_BATCH_SIZE):
            if asyncio.get_event_loop().time() > overall_deadline:
                logger.warning(
                    f"Embedding overall deadline reached after {len(all_embeddings)}/{len(texts)} texts"
                )
                break

            batch = texts[i:i + _EMBED_MAX_BATCH_SIZE]
            try:
                batch_embeddings = await asyncio.wait_for(
                    self._embed_batch(batch),
                    timeout=_EMBED_PER_TEXT_TIMEOUT * len(batch) + 5.0,
                )
                all_embeddings.extend(batch_embeddings)
            except asyncio.TimeoutError:
                logger.warning(
                    f"Embedding batch [{i}:{i+len(batch)}] timed out, "
                    f"falling back to single-text embedding"
                )
                # Fallback: embed one at a time
                for j, text in enumerate(batch):
                    if asyncio.get_event_loop().time() > overall_deadline:
                        break
                    try:
                        single = await asyncio.wait_for(
                            self._embed_batch([text]),
                            timeout=_EMBED_PER_TEXT_TIMEOUT + 5.0,
                        )
                        all_embeddings.extend(single)
                    except (asyncio.TimeoutError, Exception) as e:
                        logger.warning(f"Single-text embedding failed for item {i+j}: {e}")
                        # Return zero embedding as placeholder
                        all_embeddings.append([])
            except Exception as e:
                logger.error(f"Embedding batch [{i}:{i+len(batch)}] failed: {e}")
                # Fill with empty embeddings
                all_embeddings.extend([[] for _ in batch])

        return all_embeddings

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a small batch of texts using streaming response."""
        client = await self._get_client()

        try:
            # Use streaming to avoid buffering the entire JSON response
            async with client.stream(
                "POST",
                "/embeddings",
                json={
                    "model": self.model,
                    "input": texts,
                },
            ) as response:
                response.raise_for_status()

                # Read body with a size limit (each 4096-dim embedding ≈ 32KB)
                # For _EMBED_MAX_BATCH_SIZE texts: ~160KB max expected
                MAX_EMBED_RESPONSE = 2 * 1024 * 1024  # 2MB safety limit
                chunks = []
                total_read = 0
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    total_read += len(chunk)
                    if total_read > MAX_EMBED_RESPONSE:
                        logger.error(
                            f"Embedding response exceeded {MAX_EMBED_RESPONSE/1024/1024:.0f}MB "
                            f"safety limit (read {total_read/1024/1024:.1f}MB). Aborting."
                        )
                        raise ValueError("Embedding response too large — possible API error")
                    chunks.append(chunk)

                # Combine chunks and parse
                import json
                body = b"".join(chunks)
                data = json.loads(body)

                # Extract embeddings in order
                embeddings = []
                for item in sorted(data["data"], key=lambda x: x["index"]):
                    embeddings.append(item["embedding"])

                return embeddings
        except httpx.HTTPStatusError as e:
            logger.error(f"Embedding API HTTP error: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"Embedding API error: {e}")
            raise

    async def embed_single(self, text: str) -> list[float]:
        """Get embedding for a single text."""
        embeddings = await self.embed([text])
        return embeddings[0] if embeddings and embeddings[0] else []


# Global embedding client
_embedding_client: Optional[EmbeddingClient] = None


def get_embedding_client() -> EmbeddingClient:
    """Get the global embedding client."""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client
