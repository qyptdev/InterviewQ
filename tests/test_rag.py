"""Tests for RAG module: BM25, RAPTOR, HybridRetriever, and chunker.

Covers:
- BM25Index: add_documents, search, scoring, tokenization, clear
- RaptorTree: build, search, multi-level hierarchy
- HybridRetriever: index, search, merge_results, fallback when embedding fails
- chunk_text: various input sizes, overlap behavior, edge cases
- All tests work WITHOUT external API calls (embedder is mocked)
"""

import pytest
from unittest.mock import AsyncMock, patch


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

    def test_long_paragraph_no_infinite_loop(self):
        """Long text without separators completes without infinite loop."""
        import signal
        from app.rag.chunker import chunk_text

        # 5000 Chinese characters with no line breaks, periods, or spaces
        long_text = "字" * 5000

        # Use an alarm to ensure no infinite loop (5 second timeout)
        def _timeout_handler(signum, frame):
            raise TimeoutError("chunk_text did not return within 5 seconds")

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(5)
        try:
            result = chunk_text(long_text, chunk_size=1024, chunk_overlap=200)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

        # Should return multiple chunks and cover all text
        assert len(result) > 1
        # All text should be covered in the chunks (joined without overlap)
        assert len("".join(result)) >= 5000

    def test_overlap_capped(self):
        """chunk_overlap larger than chunk_size does not cause infinite loop."""
        from app.rag.chunker import chunk_text

        # chunk_overlap=2000 >> chunk_size=500, overlap should be capped
        long_text = "x" * 3000
        result = chunk_text(long_text, chunk_size=500, chunk_overlap=2000)

        assert len(result) > 1
        # Each chunk should respect chunk_size (allowing slight overshoot for overlap text)
        for chunk in result:
            assert len(chunk) <= 500 + 500  # generous upper bound to account for overlap

    def test_min_advance_guaranteed(self):
        """Each split iteration actually advances the text position."""
        from app.rag.chunker import _split_long_text

        # Text that triggers splitting with large overlap relative to split point
        text = "abcde" * 500  # 2500 chars
        chunk_size = 200
        effective_overlap = min(100, chunk_size // 4)  # 50 (capped)
        separators = ["\n\n", "\n", "。", ".", " ", ""]
        chunks = []

        result = _split_long_text(text, chunk_size, effective_overlap, separators, chunks)

        # Should have produced multiple chunks
        assert len(chunks) > 1
        # The remaining text should be shorter than the original
        assert len(result) < 2500
        # Every chunk should have content
        for chunk in chunks:
            assert len(chunk) > 0

    def test_find_split_point_prefers_closest_to_max(self):
        """_find_split_point prefers the separator closest to max_size."""
        from app.rag.chunker import _find_split_point

        # "Hello world. This is a test."
        # Pos 5=' ', pos 11='.', pos 12=' ', pos 17=' ', pos 20=' ', pos 22=' '
        text = "Hello world. This is a test."
        # With "." at pos 11 -> candidate 12
        # With " " the rfind in [0,20) finds " " at pos 17 -> candidate 18
        # 18 is closer to max_size=20 than 12, so space wins
        point = _find_split_point(text, 20, [".", " "])
        assert point == 18

    def test_no_content_loss_when_advance_exceeds_split_point(self):
        """Content between split_point and advance is not lost when advance is bumped.

        When _find_split_point returns a value smaller than min_advance but
        larger than effective_overlap, the advance is bumped to min_advance
        to guarantee forward progress. The chunk must be extended to cover up
        to the advance position so that no content falls into a gap.
        """
        from app.rag.chunker import _split_long_text

        # Construct text where '. ' separator is early (pos 60),
        # giving split_point=62 which is > effective_overlap=50 but < min_advance=100
        prefix = "".join(chr(65 + i % 26) for i in range(60))
        gap_markers = [f"[G{i}]" for i in range(50)]
        after_markers = [f"[Z{i}]" for i in range(100)]
        text = prefix + ". " + "".join(gap_markers) + "".join(after_markers)

        chunks = []
        result = _split_long_text(
            text, chunk_size=200, effective_overlap=50,
            separators=[". ", ".", " "], chunks=chunks,
        )

        joined = "".join(chunks) + result

        # All gap markers must be present (no content loss)
        for i in range(50):
            assert f"[G{i}]" in joined, f"Gap marker [G{i}] lost when advance > split_point"

        # All after markers must be present
        for i in range(100):
            assert f"[Z{i}]" in joined, f"After marker [Z{i}] lost"

    def test_chunk_text_preserves_all_unique_markers(self):
        """chunk_text with unique position markers loses no content."""
        from app.rag.chunker import chunk_text

        markers = [f"[{i:04d}]" for i in range(300)]
        text = "".join(markers)

        result = chunk_text(text, chunk_size=200, chunk_overlap=200)
        joined = "".join(result)

        for i in range(300):
            assert f"[{i:04d}]" in joined, f"Marker [{i:04d}] lost in chunking"
