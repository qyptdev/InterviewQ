"""Hybrid retriever combining BM25 and vector search.

Memory-safety: The index() method wraps embedding in a try/except so that
a slow/hanging embedding API never blocks the generation pipeline.  When
embeddings are unavailable, search falls back to BM25 + Raptor only.
"""

import logging
from typing import Optional

from app.rag.bm25_index import BM25Index
from app.rag.raptor_tree import RaptorTree
from app.rag.embedder import get_embedding_client

logger = logging.getLogger(__name__)

# Max time to wait for the embedding step during indexing
_EMBED_INDEX_TIMEOUT = 30.0  # seconds


class HybridRetriever:
    """Hybrid retriever combining BM25 and vector search."""

    def __init__(self, alpha: float = 0.5):
        self.alpha = alpha  # Weight for BM25 vs vector (0 = all vector, 1 = all BM25)
        self.bm25 = BM25Index()
        self.raptor = RaptorTree()
        self.documents: list[dict] = []
        self.embeddings: Optional[list[list[float]]] = None

    async def index(self, documents: list[dict]) -> None:
        """Index documents for hybrid search.

        Embedding generation is wrapped in a timeout so that a slow
        or failing embedding API does not block the pipeline.
        """
        import asyncio

        self.documents = documents

        # Build BM25 index
        self.bm25.add_documents(documents)
        logger.info(f"BM25 index built with {len(documents)} documents")

        # Build RAPTOR tree
        self.raptor.build(documents)
        logger.info("RAPTOR tree built")

        # Generate embeddings with timeout (if embedding client available)
        self.embeddings = None  # Reset
        try:
            embedder = get_embedding_client()
            texts = [doc.get("content", "") for doc in documents]
            self.embeddings = await asyncio.wait_for(
                embedder.embed(texts),
                timeout=_EMBED_INDEX_TIMEOUT,
            )
            logger.info(f"Embeddings generated for {len(documents)} documents")
        except asyncio.TimeoutError:
            logger.warning(
                f"Embedding generation timed out ({_EMBED_INDEX_TIMEOUT}s), "
                f"falling back to BM25+Raptor only"
            )
            self.embeddings = None
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            self.embeddings = None

    async def search(self, query: str, top_k: int = 10) -> list[dict]:
        """Search using hybrid approach."""
        results = []

        # BM25 search
        bm25_results = self.bm25.search(query, top_k=top_k * 2)
        for r in bm25_results:
            r["search_method"] = "bm25"
            results.append(r)

        # RAPTOR search
        raptor_results = self.raptor.search(query, top_k=top_k * 2)
        for r in raptor_results:
            r["search_method"] = "raptor"
            results.append(r)

        # Vector search (if embeddings available)
        if self.embeddings:
            vector_results = await self._vector_search(query, top_k=top_k * 2)
            for r in vector_results:
                r["search_method"] = "vector"
                results.append(r)

        # Merge and deduplicate
        merged = self._merge_results(results, top_k)
        return merged

    async def _vector_search(self, query: str, top_k: int) -> list[dict]:
        """Search using vector similarity."""
        if not self.embeddings or not self.documents:
            return []

        try:
            embedder = get_embedding_client()
            query_embedding = await embedder.embed_single(query)

            # Calculate cosine similarities
            scored = []
            for i, doc_embedding in enumerate(self.embeddings):
                similarity = self._cosine_similarity(query_embedding, doc_embedding)
                scored.append((similarity, i))

            scored.sort(reverse=True)
            results = []
            for sim, idx in scored[:top_k]:
                if sim > 0:
                    result = self.documents[idx].copy()
                    result["vector_score"] = sim
                    results.append(result)

            return results
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _merge_results(self, results: list[dict], top_k: int) -> list[dict]:
        """Merge results from different search methods."""
        # Group by content
        content_groups: dict[str, list[dict]] = {}
        for r in results:
            content = r.get("content", "")
            if content not in content_groups:
                content_groups[content] = []
            content_groups[content].append(r)

        # Calculate combined scores
        scored = []
        for content, group in content_groups.items():
            bm25_score = sum(r.get("bm25_score", 0) for r in group if "bm25_score" in r)
            vector_score = sum(r.get("vector_score", 0) for r in group if "vector_score" in r)

            # Normalize scores
            bm25_count = sum(1 for r in group if "bm25_score" in r)
            vector_count = sum(1 for r in group if "vector_score" in r)

            avg_bm25 = bm25_score / bm25_count if bm25_count > 0 else 0
            avg_vector = vector_score / vector_count if vector_count > 0 else 0

            # Combined score
            combined_score = self.alpha * avg_bm25 + (1 - self.alpha) * avg_vector

            result = group[0].copy()
            result["combined_score"] = combined_score
            result["search_methods"] = list(set(r.get("search_method", "") for r in group))
            scored.append(result)

        scored.sort(reverse=True, key=lambda x: x.get("combined_score", 0))
        return scored[:top_k]

    def clear(self) -> None:
        """Clear all indices."""
        self.bm25.clear()
        self.raptor = RaptorTree()
        self.documents.clear()
        self.embeddings = None
