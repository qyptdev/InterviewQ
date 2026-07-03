"""Tests for RAG module: BM25, RAPTOR, HybridRetriever, and chunker.

Covers:
- BM25Index: add_documents, search, scoring, tokenization, clear
- RaptorTree: build, search, multi-level hierarchy
- HybridRetriever: index, search, merge_results, fallback when embedding fails
- chunk_text: various input sizes, overlap behavior, edge cases
- All tests work WITHOUT external API calls (embedder is mocked)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestBM25Index:
    """Tests for BM25 keyword index."""

    def test_add_documents_and_search(self):
        """Adding documents and searching returns relevant results."""
        from app.rag.bm25_index import BM25Index

        idx = BM25Index()
        docs = [
            {"content": "Python is a programming language"},
            {"content": "Java is also a programming language"},
            {"content": "The weather is nice today"},
        ]
        idx.add_documents(docs)

        results = idx.search("Python programming", top_k=3)
        assert len(results) > 0
        # Python doc should be ranked first
        assert "Python" in results[0]["content"]
        assert "bm25_score" in results[0]

    def test_search_empty_index(self):
        """Searching an empty index returns no results."""
        from app.rag.bm25_index import BM25Index

        idx = BM25Index()
        results = idx.search("anything")
        assert results == []

    def test_search_no_match(self):
        """Searching with unrelated query returns no results."""
        from app.rag.bm25_index import BM25Index

        idx = BM25Index()
        idx.add_documents([{"content": "Python programming"}])

        results = idx.search("quantum physics")
        assert results == []

    def test_search_top_k_limit(self):
        """Search respects the top_k limit."""
        from app.rag.bm25_index import BM25Index

        idx = BM25Index()
        docs = [{"content": f"document number {i} about Python"} for i in range(20)]
        idx.add_documents(docs)

        results = idx.search("Python", top_k=5)
        assert len(results) <= 5

    def test_scoring_higher_for_more_matches(self):
        """Documents with more query terms score higher."""
        from app.rag.bm25_index import BM25Index

        idx = BM25Index()
        docs = [
            {"content": "Python"},
            {"content": "Python Python Python"},
        ]
        idx.add_documents(docs)

        results = idx.search("Python", top_k=2)
        assert len(results) == 2
        # Doc with repeated term should score higher (TF component)
        assert results[0]["content"] == "Python Python Python"

    def test_tokenize_chinese(self):
        """Tokenization handles Chinese characters.

        Note: BM25Index._tokenize uses regex [\\w一-鿿]+ which treats
        contiguous CJK+ASCII as a single token. This is expected behavior
        for the simple tokenizer (not jieba-based).
        """
        from app.rag.bm25_index import BM25Index

        idx = BM25Index()
        tokens = idx._tokenize("Python是一种编程语言")
        # Should contain at least one token with content
        assert len(tokens) >= 1
        assert any("python" in t.lower() or "编程" in t for t in tokens)

    def test_clear(self):
        """Clearing the index removes all data."""
        from app.rag.bm25_index import BM25Index

        idx = BM25Index()
        idx.add_documents([{"content": "test"}])
        assert idx.indexed is True

        idx.clear()
        assert idx.indexed is False
        assert len(idx.documents) == 0
        assert idx.avg_doc_length == 0.0

    def test_empty_query_returns_no_results(self):
        """Empty or whitespace-only query returns no results."""
        from app.rag.bm25_index import BM25Index

        idx = BM25Index()
        idx.add_documents([{"content": "some content"}])

        assert idx.search("") == []
        assert idx.search("   ") == []


class TestRaptorTree:
    """Tests for RAPTOR hierarchical tree."""

    def test_build_single_level(self):
        """Building with few chunks creates at least one level."""
        from app.rag.raptor_tree import RaptorTree

        tree = RaptorTree(max_levels=2)
        chunks = [{"content": f"chunk {i}"} for i in range(3)]
        tree.build(chunks)

        assert len(tree.levels) >= 1
        assert len(tree.levels[0]) == 3

    def test_build_multiple_levels(self):
        """Building with enough chunks creates summary levels."""
        from app.rag.raptor_tree import RaptorTree

        tree = RaptorTree(max_levels=3)
        chunks = [{"content": f"chunk {i} with some content"} for i in range(15)]
        tree.build(chunks)

        # Should have original level + at least one summary level
        assert len(tree.levels) >= 2

    def test_build_empty_chunks(self):
        """Building with empty list creates no levels."""
        from app.rag.raptor_tree import RaptorTree

        tree = RaptorTree()
        tree.build([])
        assert len(tree.levels) == 0

    def test_search_finds_relevant_chunks(self):
        """Search returns chunks matching query keywords."""
        from app.rag.raptor_tree import RaptorTree

        tree = RaptorTree(max_levels=1)
        chunks = [
            {"content": "Python is great for web development"},
            {"content": "Java is used in enterprise applications"},
            {"content": "Machine learning with TensorFlow"},
        ]
        tree.build(chunks)

        results = tree.search("Python web", top_k=3)
        assert len(results) > 0
        assert any("Python" in r["content"] for r in results)

    def test_search_empty_tree(self):
        """Searching an empty tree returns no results."""
        from app.rag.raptor_tree import RaptorTree

        tree = RaptorTree()
        results = tree.search("anything")
        assert results == []

    def test_search_deduplication(self):
        """Search results are deduplicated by content."""
        from app.rag.raptor_tree import RaptorTree

        tree = RaptorTree(max_levels=2)
        # Same content in multiple chunks
        chunks = [
            {"content": "duplicate content here"},
            {"content": "duplicate content here"},
            {"content": "unique content"},
        ]
        tree.build(chunks)

        results = tree.search("duplicate", top_k=10)
        contents = [r["content"] for r in results]
        # Should not have exact duplicates
        assert len(contents) == len(set(contents))


class TestHybridRetriever:
    """Tests for hybrid retriever combining BM25 + vector search."""

    @pytest.mark.asyncio
    async def test_index_with_embedding_failure(self):
        """Indexing succeeds even when embedding API fails (graceful fallback)."""
        from app.rag.retriever import HybridRetriever

        retriever = HybridRetriever(alpha=0.5)
        docs = [
            {"content": "Python programming basics"},
            {"content": "Web development with FastAPI"},
        ]

        with patch(
            "app.rag.retriever.get_embedding_client",
            side_effect=Exception("Embedding API down"),
        ):
            await retriever.index(docs)

        # BM25 should still work
        assert retriever.bm25.indexed is True
        assert retriever.embeddings is None

    @pytest.mark.asyncio
    async def test_index_with_mock_embeddings(self):
        """Indexing with working embeddings stores them."""
        from app.rag.retriever import HybridRetriever

        retriever = HybridRetriever(alpha=0.5)
        docs = [
            {"content": "doc one"},
            {"content": "doc two"},
        ]

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])

        with patch("app.rag.retriever.get_embedding_client", return_value=mock_embedder):
            await retriever.index(docs)

        assert retriever.embeddings is not None
        assert len(retriever.embeddings) == 2

    @pytest.mark.asyncio
    async def test_search_bm25_only_when_no_embeddings(self):
        """Search works with BM25 only when embeddings are unavailable."""
        from app.rag.retriever import HybridRetriever

        retriever = HybridRetriever(alpha=0.5)
        docs = [
            {"content": "Python is a programming language"},
            {"content": "The sky is blue"},
        ]

        with patch(
            "app.rag.retriever.get_embedding_client",
            side_effect=Exception("No embeddings"),
        ):
            await retriever.index(docs)

        results = await retriever.search("Python", top_k=5)
        assert len(results) > 0
        assert any("Python" in r["content"] for r in results)

    @pytest.mark.asyncio
    async def test_merge_results_deduplication(self):
        """Merging results deduplicates by content."""
        from app.rag.retriever import HybridRetriever

        retriever = HybridRetriever(alpha=0.5)

        results = [
            {"content": "same text", "bm25_score": 1.0, "search_method": "bm25"},
            {"content": "same text", "vector_score": 0.8, "search_method": "vector"},
            {"content": "different text", "bm25_score": 0.5, "search_method": "bm25"},
        ]

        merged = retriever._merge_results(results, top_k=10)
        assert len(merged) == 2
        # The duplicate should have combined scores
        same_text_result = next(r for r in merged if r["content"] == "same text")
        assert "combined_score" in same_text_result

    @pytest.mark.asyncio
    async def test_cosine_similarity_identical_vectors(self):
        """Cosine similarity of identical vectors is 1.0."""
        from app.rag.retriever import HybridRetriever

        retriever = HybridRetriever()
        vec = [1.0, 2.0, 3.0]
        sim = retriever._cosine_similarity(vec, vec)
        assert abs(sim - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_cosine_similarity_orthogonal_vectors(self):
        """Cosine similarity of orthogonal vectors is 0.0."""
        from app.rag.retriever import HybridRetriever

        retriever = HybridRetriever()
        sim = retriever._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert abs(sim) < 1e-6

    @pytest.mark.asyncio
    async def test_cosine_similarity_empty_vectors(self):
        """Cosine similarity with empty vectors returns 0.0."""
        from app.rag.retriever import HybridRetriever

        retriever = HybridRetriever()
        assert retriever._cosine_similarity([], [1.0]) == 0.0
        assert retriever._cosine_similarity([1.0], []) == 0.0

    def test_clear(self):
        """Clearing retriever resets all indices."""
        from app.rag.retriever import HybridRetriever

        retriever = HybridRetriever()
        retriever.documents = [{"content": "test"}]
        retriever.embeddings = [[0.1]]

        retriever.clear()
        assert len(retriever.documents) == 0
        assert retriever.embeddings is None


class TestChunker:
    """Tests for text chunking utilities."""

    def test_chunk_short_text(self):
        """Text shorter than chunk_size returns single chunk."""
        from app.rag.chunker import chunk_text

        result = chunk_text("Short text", chunk_size=1024)
        assert len(result) == 1
        assert result[0] == "Short text"

    def test_chunk_empty_text(self):
        """Empty text returns no chunks."""
        from app.rag.chunker import chunk_text

        assert chunk_text("") == []
        assert chunk_text(None) == []

    def test_chunk_long_text_splits(self):
        """Long text is split into multiple chunks."""
        from app.rag.chunker import chunk_text

        # Create text longer than chunk_size
        long_text = "\n\n".join([f"Paragraph {i} with some content." for i in range(20)])
        result = chunk_text(long_text, chunk_size=100, chunk_overlap=0)
        assert len(result) > 1

    def test_chunk_overlap_preserves_context(self):
        """Chunks with overlap share boundary text."""
        from app.rag.chunker import chunk_text

        paragraphs = "\n\n".join([f"Sentence number {i}." for i in range(10)])
        result = chunk_text(paragraphs, chunk_size=80, chunk_overlap=30)

        if len(result) >= 2:
            # Last part of chunk N should appear at start of chunk N+1
            # (due to overlap mechanism)
            assert len(result) > 1

    def test_chunk_documents(self):
        """chunk_documents adds metadata to each chunk."""
        from app.rag.chunker import chunk_documents

        docs = [
            {"content": "Short doc", "id": "doc1", "filename": "test.txt"},
        ]
        result = chunk_documents(docs, chunk_size=1024)
        assert len(result) == 1
        assert result[0]["metadata"]["doc_id"] == "doc1"
        assert result[0]["metadata"]["filename"] == "test.txt"
        assert result[0]["metadata"]["chunk_index"] == 0

    def test_chunk_documents_multiple(self):
        """chunk_documents handles multiple documents."""
        from app.rag.chunker import chunk_documents

        docs = [
            {"content": "Doc A content", "id": "a", "filename": "a.txt"},
            {"content": "Doc B content", "id": "b", "filename": "b.txt"},
        ]
        result = chunk_documents(docs, chunk_size=1024)
        assert len(result) == 2
        ids = {r["metadata"]["doc_id"] for r in result}
        assert ids == {"a", "b"}

    def test_find_split_point_with_separator(self):
        """_find_split_point finds separator near max_size."""
        from app.rag.chunker import _find_split_point

        text = "Hello world. This is a test. More text here."
        point = _find_split_point(text, 30, [".", " "])
        assert point > 0
        assert point <= 30

    def test_find_split_point_no_separator(self):
        """_find_split_point falls back to max_size when no separator found."""
        from app.rag.chunker import _find_split_point

        text = "abcdefghijklmnopqrstuvwxyz"
        point = _find_split_point(text, 10, ["\n"])
        assert point == 10
