"""RAPTOR tree for hierarchical retrieval."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RaptorTree:
    """Simple RAPTOR tree for hierarchical document retrieval."""

    def __init__(self, max_levels: int = 2):
        self.max_levels = max_levels
        self.levels: list[list[dict]] = []

    def build(self, chunks: list[dict]) -> None:
        """Build the RAPTOR tree from document chunks."""
        if not chunks:
            return

        # Level 0: original chunks
        self.levels = [chunks]

        # Build summary levels
        current_level = chunks
        for level in range(1, self.max_levels):
            summaries = self._create_summaries(current_level)
            if not summaries:
                break
            self.levels.append(summaries)
            current_level = summaries

        logger.info(f"RAPTOR tree built with {len(self.levels)} levels")

    def _create_summaries(self, chunks: list[dict], group_size: int = 5) -> list[dict]:
        """Create summary nodes by grouping chunks."""
        summaries = []

        for i in range(0, len(chunks), group_size):
            group = chunks[i:i + group_size]

            # Combine content
            combined_content = "\n\n".join(c.get("content", "") for c in group)

            # Create summary (simple concatenation for now)
            # In production, use LLM to generate proper summaries
            summary = {
                "content": combined_content[:500],  # Truncate for summary
                "metadata": {
                    "level": len(self.levels),
                    "children": [c.get("metadata", {}).get("chunk_index", i + j) for j, c in enumerate(group)],
                    "is_summary": True,
                },
            }
            summaries.append(summary)

        return summaries

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search the tree top-down."""
        if not self.levels:
            return []

        # Start from top level
        results = []
        for level in reversed(self.levels):
            # Simple keyword matching (can be enhanced with embeddings)
            level_results = self._search_level(query, level, top_k)
            results.extend(level_results)

        # Deduplicate and limit
        seen = set()
        unique_results = []
        for r in results:
            content = r.get("content", "")
            if content not in seen:
                seen.add(content)
                unique_results.append(r)

        return unique_results[:top_k]

    def _search_level(self, query: str, level: list[dict], top_k: int) -> list[dict]:
        """Search within a single level."""
        query_lower = query.lower()
        scored = []

        for chunk in level:
            content = chunk.get("content", "").lower()
            # Simple relevance scoring
            score = sum(1 for word in query_lower.split() if word in content)
            if score > 0:
                scored.append((score, chunk))

        scored.sort(reverse=True, key=lambda x: x[0])
        return [chunk for _, chunk in scored[:top_k]]
