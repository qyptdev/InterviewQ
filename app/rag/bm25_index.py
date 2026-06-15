"""BM25 keyword index for hybrid retrieval."""

import logging
import math
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)


class BM25Index:
    """Simple BM25 index for keyword-based retrieval."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents: list[dict] = []
        self.doc_lengths: list[int] = []
        self.avg_doc_length: float = 0.0
        self.doc_freqs: dict[str, int] = {}
        self.indexed = False

    def add_documents(self, documents: list[dict]) -> None:
        """Add documents to the index."""
        for doc in documents:
            content = doc.get("content", "")
            tokens = self._tokenize(content)

            self.documents.append(doc)
            self.doc_lengths.append(len(tokens))

            # Update document frequencies
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self.doc_freqs[token] = self.doc_freqs.get(token, 0) + 1

        # Calculate average document length
        if self.doc_lengths:
            self.avg_doc_length = sum(self.doc_lengths) / len(self.doc_lengths)

        self.indexed = True

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        """Search for documents matching the query."""
        if not self.indexed or not self.documents:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # Calculate scores
        scores = []
        for i, doc in enumerate(self.documents):
            score = self._calculate_score(query_tokens, i)
            scores.append((score, i))

        # Sort by score descending
        scores.sort(reverse=True)

        # Return top-k results
        results = []
        for score, idx in scores[:top_k]:
            if score > 0:
                result = self.documents[idx].copy()
                result["bm25_score"] = score
                results.append(result)

        return results

    def _calculate_score(self, query_tokens: list[str], doc_idx: int) -> float:
        """Calculate BM25 score for a document."""
        doc_tokens = self._tokenize(self.documents[doc_idx].get("content", ""))
        doc_len = self.doc_lengths[doc_idx]
        tf_counter = Counter(doc_tokens)

        score = 0.0
        for token in query_tokens:
            if token not in self.doc_freqs:
                continue

            # Term frequency
            tf = tf_counter.get(token, 0)

            # Inverse document frequency
            df = self.doc_freqs[token]
            idf = math.log((len(self.documents) - df + 0.5) / (df + 0.5) + 1)

            # BM25 formula
            tf_norm = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_length))

            score += idf * tf_norm

        return score

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenization (split by spaces and punctuation)."""
        import re
        # Split by non-alphanumeric characters (including CJK)
        tokens = re.findall(r'[\w一-鿿]+', text.lower())
        return tokens

    def clear(self) -> None:
        """Clear the index."""
        self.documents.clear()
        self.doc_lengths.clear()
        self.avg_doc_length = 0.0
        self.doc_freqs.clear()
        self.indexed = False
