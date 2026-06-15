"""Validate node for question quality check."""

import logging
from typing import Optional

import jieba

from app.core.state_models import QuestionBatch, ValidationResult

logger = logging.getLogger(__name__)


def validate_question_batch(batch: QuestionBatch) -> ValidationResult:
    """Validate a batch of questions for quality."""
    issues = []
    suggestions = []

    if not batch.questions:
        issues.append("批次中没有题目")
        return ValidationResult(is_valid=False, issues=issues)

    # Check each question
    titles_seen = set()
    for i, q in enumerate(batch.questions):
        # Safe title extraction: handle list/str types from LLM
        raw_title = q.get("title", "")
        if isinstance(raw_title, list):
            title = " ".join(str(t) for t in raw_title).strip()
            q["title"] = title  # Write back corrected value
        else:
            title = str(raw_title).strip()

        # Safe expected_answer extraction
        raw_answer = q.get("expected_answer", "")
        if isinstance(raw_answer, list):
            answer = " ".join(str(a) for a in raw_answer).strip()
            q["expected_answer"] = answer  # Write back corrected value
        else:
            answer = str(raw_answer).strip()

        # Check for empty titles
        if not title:
            issues.append(f"题目 {i+1} 标题为空")

        # Check for duplicates within batch
        if title in titles_seen:
            issues.append(f"题目 {i+1} 与批次内其他题目重复")
        titles_seen.add(title)

        # Check for very short titles
        if len(title) < 10:
            suggestions.append(f"题目 {i+1} 标题过短，建议扩展")

        # Check for expected answer
        if not answer:
            suggestions.append(f"题目 {i+1} 缺少参考答案")

    is_valid = len(issues) == 0

    return ValidationResult(
        is_valid=is_valid,
        issues=issues,
        suggestions=suggestions,
    )


def _safe_title(q: dict) -> str:
    """Extract title as string, handling list/str types."""
    raw = q.get("title", "")
    if isinstance(raw, list):
        return " ".join(str(t) for t in raw).strip()
    return str(raw).strip()


def _is_duplicate_of_any(
    question: dict,
    existing_unique: list[dict],
    threshold: float,
) -> bool:
    """Check if *question* is a duplicate of any in *existing_unique*."""
    q_title = _safe_title(question)
    for uq in existing_unique:
        uq_title = _safe_title(uq)
        if _simple_similarity(q_title, uq_title) > threshold:
            return True
    return False


def deduplicate_questions(questions: list[dict], threshold: float = 0.85) -> list[dict]:
    """Remove duplicate questions based on title similarity.

    This is a full-rewrite dedup: compares every question against every
    previously-seen unique question.  For incremental dedup (only new
    questions vs already-confirmed unique set), use
    :func:`deduplicate_new_questions` instead.
    """
    if not questions:
        return []

    unique_questions = [questions[0]]

    for q in questions[1:]:
        if not _is_duplicate_of_any(q, unique_questions, threshold):
            unique_questions.append(q)

    return unique_questions


def deduplicate_new_questions(
    new_questions: list[dict],
    existing_unique: list[dict],
    threshold: float = 0.85,
) -> list[dict]:
    """Incremental dedup: only check *new* questions against the existing unique set.

    This avoids O(n²) re-scanning of already-confirmed-unique questions.
    Returns the merged list of unique questions (existing + newly-accepted).

    Args:
        new_questions: Freshly generated questions to check.
        existing_unique: Previously confirmed-unique questions.
        threshold: Jaccard similarity threshold (default 0.85).

    Returns:
        Merged list of unique questions.
    """
    accepted = list(existing_unique)  # copy to avoid mutating caller's list

    for q in new_questions:
        if not _is_duplicate_of_any(q, accepted, threshold):
            accepted.append(q)

    return accepted


def _simple_similarity(text1: str, text2: str) -> float:
    """Calculate text similarity using word-level Jaccard index.

    Uses jieba segmentation for Chinese text instead of character-level
    comparison. Character-level Jaccard is ineffective for Chinese because
    common characters (e.g., 的、是、在) appear in many unrelated sentences,
    leading to artificially high similarity scores. Word-level tokenization
    provides semantically meaningful units for accurate deduplication.
    """
    if not text1 or not text2:
        return 0.0

    # Tokenize using jieba; filter out whitespace-only tokens
    words1 = set(w for w in jieba.cut(text1) if w.strip())
    words2 = set(w for w in jieba.cut(text2) if w.strip())

    if not words1 or not words2:
        return 0.0

    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return intersection / union if union > 0 else 0.0
