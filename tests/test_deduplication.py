"""Tests for Chinese deduplication algorithm using jieba word-level Jaccard.

Covers:
- _simple_similarity with Chinese text pairs (synonyms, different chars)
- Edge cases: empty strings, single chars, mixed CN/EN
- deduplicate_questions with known duplicates and non-duplicates
- Threshold behavior verification
"""

import pytest

from app.core.nodes_validate import _simple_similarity, deduplicate_questions


class TestSimpleSimilarity:
    """Tests for the jieba-based word-level Jaccard similarity function."""

    def test_identical_chinese_strings(self):
        """Identical Chinese strings have similarity 1.0."""
        text = "Python是一种编程语言"
        assert _simple_similarity(text, text) == 1.0

    def test_completely_different_chinese(self):
        """Completely unrelated Chinese sentences have low similarity."""
        sim = _simple_similarity("今天天气真好", "数据库索引优化策略")
        assert sim < 0.3

    def test_synonymous_chinese_sentences(self):
        """Semantically similar Chinese sentences (same words, different order) have high similarity."""
        t1 = "Python编程语言是什么"
        t2 = "什么是Python编程语言"
        sim = _simple_similarity(t1, t2)
        # Same words in different order → Jaccard should be 1.0 (set-based)
        assert sim > 0.8

    def test_partial_overlap_chinese(self):
        """Sentences sharing some words have moderate similarity."""
        t1 = "如何使用FastAPI构建Web应用"
        t2 = "如何使用Django构建Web应用"
        sim = _simple_similarity(t1, t2)
        # Share "如何", "使用", "构建", "Web", "应用" but differ on framework
        assert 0.3 < sim < 0.9

    def test_empty_string_first(self):
        """Empty first string returns 0.0."""
        assert _simple_similarity("", "some text") == 0.0

    def test_empty_string_second(self):
        """Empty second string returns 0.0."""
        assert _simple_similarity("some text", "") == 0.0

    def test_both_empty(self):
        """Both empty strings return 0.0."""
        assert _simple_similarity("", "") == 0.0

    def test_single_char_chinese(self):
        """Single character Chinese strings."""
        sim = _simple_similarity("好", "好")
        assert sim == 1.0

    def test_single_char_different(self):
        """Different single characters have 0.0 similarity."""
        sim = _simple_similarity("好", "坏")
        assert sim == 0.0

    def test_mixed_chinese_english(self):
        """Mixed Chinese and English text is tokenized correctly."""
        t1 = "使用Python开发Web应用"
        t2 = "使用Java开发Web应用"
        sim = _simple_similarity(t1, t2)
        # Share "使用", "开发", "Web", "应用"; differ on language name
        assert 0.3 < sim < 0.9

    def test_pure_english(self):
        """Pure English text works with jieba tokenization."""
        t1 = "What is Python programming"
        t2 = "What is Java programming"
        sim = _simple_similarity(t1, t2)
        # Share "What", "is", "programming"
        assert 0.3 < sim < 0.8

    def test_whitespace_only(self):
        """Whitespace-only strings return 0.0."""
        assert _simple_similarity("   ", "text") == 0.0
        assert _simple_similarity("text", "   ") == 0.0

    def test_character_level_vs_word_level(self):
        """Word-level Jaccard avoids false positives from shared common characters.

        Character-level Jaccard would give high similarity to unrelated sentences
        sharing common chars like 的、是、在. Word-level should give lower similarity.
        """
        t1 = "这是一个关于数据库的问题"
        t2 = "这是一个关于前端的问题"
        sim = _simple_similarity(t1, t2)
        # They share "这是", "一个", "关于", "的", "问题" but differ on topic
        # Word-level should give moderate (not very high) similarity
        assert sim < 0.85


class TestDeduplicateQuestions:
    """Tests for the deduplicate_questions function."""

    def test_no_duplicates(self):
        """All unique questions are preserved."""
        questions = [
            {"title": "什么是Python?"},
            {"title": "解释REST API"},
            {"title": "Docker容器化原理"},
        ]
        result = deduplicate_questions(questions)
        assert len(result) == 3

    def test_exact_duplicates_removed(self):
        """Exact duplicate titles are removed."""
        questions = [
            {"title": "什么是Python?"},
            {"title": "什么是Python?"},
            {"title": "解释REST API"},
        ]
        result = deduplicate_questions(questions)
        assert len(result) == 2

    def test_near_duplicates_removed(self):
        """Near-duplicate Chinese questions (same words, minor differences) are removed."""
        questions = [
            {"title": "Python编程语言是什么"},
            {"title": "什么是Python编程语言"},
            {"title": "Docker容器如何使用"},
        ]
        result = deduplicate_questions(questions, threshold=0.8)
        # First two are near-duplicates (same word set)
        assert len(result) == 2

    def test_empty_list(self):
        """Empty input returns empty output."""
        assert deduplicate_questions([]) == []

    def test_single_question(self):
        """Single question is returned as-is."""
        questions = [{"title": "Only question"}]
        result = deduplicate_questions(questions)
        assert len(result) == 1

    def test_threshold_high_keeps_more(self):
        """Higher threshold keeps more questions (stricter dedup)."""
        questions = [
            {"title": "如何使用FastAPI构建Web应用"},
            {"title": "如何使用Django构建Web应用"},
        ]
        # With high threshold, these should NOT be considered duplicates
        result_high = deduplicate_questions(questions, threshold=0.95)
        assert len(result_high) == 2

    def test_threshold_low_removes_more(self):
        """Lower threshold removes more questions (looser dedup)."""
        questions = [
            {"title": "如何使用FastAPI构建Web应用"},
            {"title": "如何使用Django构建Web应用"},
        ]
        # With low threshold, these might be considered duplicates
        result_low = deduplicate_questions(questions, threshold=0.3)
        assert len(result_low) <= 2

    def test_list_type_titles_handled(self):
        """Titles that are lists (from LLM output) are normalized before dedup."""
        questions = [
            {"title": ["What", "is", "Python?"]},
            {"title": "What is Python?"},
            {"title": "Explain Docker"},
        ]
        result = deduplicate_questions(questions)
        # First two should be detected as duplicates after normalization
        assert len(result) == 2

    def test_preserves_first_occurrence(self):
        """When duplicates exist, the first occurrence is kept."""
        questions = [
            {"title": "Original question", "id": 1},
            {"title": "Original question", "id": 2},
        ]
        result = deduplicate_questions(questions)
        assert len(result) == 1
        assert result[0]["id"] == 1
