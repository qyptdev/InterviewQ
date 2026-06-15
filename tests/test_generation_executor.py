"""Tests for generation_executor.py and incremental dedup.

Covers:
  - BatchResult creation
  - _generate_single_batch (mocked LLM)
  - execute_pass1 sequential and concurrent paths
  - execute_gap_fill incremental dedup
  - deduplicate_new_questions
  - _resolve_resume_ratio
"""

import asyncio
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import (
    MAX_QUESTION_COUNT,
    MAX_BATCH_SIZE,
    MAX_GENERATION_MULTIPLIER,
    MAX_SUPPLEMENT_ROUNDS,
    OVER_REQUEST_FACTOR,
    RESUME_QUESTION_RATIOS,
)
from app.core.generation_executor import (
    BatchResult,
    execute_pass1,
    execute_gap_fill,
    _generate_single_batch,
)
from app.core.nodes_validate import (
    deduplicate_questions,
    deduplicate_new_questions,
)
from app.core.graph_plan_execute import (
    _resolve_resume_ratio,
)
from app.core.state_models import QuestionPlan, QuestionBatch, ValidationResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_plan(total_batches=2, batch_size=5, concurrency=1) -> QuestionPlan:
    return QuestionPlan(
        job_title="软件工程师",
        resume_summary="测试简历",
        jd_requirements="3年经验",
        question_types=["项目深挖"],
        total_batches=total_batches,
        batch_size=batch_size,
        concurrency=concurrency,
    )


def _make_batch_questions(count=5, start_idx=0) -> list[dict]:
    return [
        {"title": f"测试题目 {i+start_idx}", "difficulty": "medium", "expected_answer": "答案"}
        for i in range(count)
    ]


def _mode_config(overrides=None):
    cfg = {
        "temperature": 0.7,
        "max_validation_retries": 2,
        "validation_strict": True,
    }
    if overrides:
        cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# Test BatchResult
# ---------------------------------------------------------------------------

class TestBatchResult:
    def test_basic_creation(self):
        r = BatchResult(
            questions=[{"title": "Q1"}],
            batch_index=0,
            mode="resume",
            is_valid=True,
            llm_calls_used=1,
        )
        assert r.questions == [{"title": "Q1"}]
        assert r.batch_index == 0
        assert r.mode == "resume"
        assert r.is_valid is True
        assert r.llm_calls_used == 1


# ---------------------------------------------------------------------------
# Test _resolve_resume_ratio
# ---------------------------------------------------------------------------

class TestResolveResumeRatio:
    def test_full_resume(self):
        ratio = _resolve_resume_ratio("A" * 300, "JD")
        assert ratio == RESUME_QUESTION_RATIOS["full_resume"]  # 0.7

    def test_partial_resume(self):
        ratio = _resolve_resume_ratio("短简历", "JD")
        assert ratio == RESUME_QUESTION_RATIOS["partial_resume"]  # 0.3

    def test_job_only(self):
        ratio = _resolve_resume_ratio("", "JD")
        assert ratio == RESUME_QUESTION_RATIOS["job_only"]  # 0.0

    def test_empty_both(self):
        ratio = _resolve_resume_ratio("", "")
        assert ratio == 0.0


# ---------------------------------------------------------------------------
# Test deduplicate_new_questions (incremental)
# ---------------------------------------------------------------------------

class TestDeduplicateNewQuestions:
    def test_empty_new(self):
        existing = [{"title": "已有题"}]
        result = deduplicate_new_questions([], existing)
        assert result == existing

    def test_empty_existing(self):
        new = [{"title": "新题"}]
        result = deduplicate_new_questions(new, [])
        assert len(result) == 1
        assert result[0]["title"] == "新题"

    def test_incremental_no_redo(self):
        """Incremental dedup should not re-check already-confirmed unique questions."""
        existing = [{"title": "已有题A"}, {"title": "已有题B"}]
        new = [{"title": "全新题C"}, {"title": "已有题A"}]
        result = deduplicate_new_questions(new, existing, threshold=0.85)
        titles = [q["title"] for q in result]
        assert "已有题A" in titles
        assert "全新题C" in titles
        # The duplicate should not appear twice
        assert titles.count("已有题A") == 1


# ---------------------------------------------------------------------------
# Test _generate_single_batch
# ---------------------------------------------------------------------------

class TestGenerateSingleBatch:
    @pytest.mark.asyncio
    async def test_sequential_valid(self):
        """Single batch: valid on first attempt."""
        plan = _make_plan(total_batches=1, batch_size=3)
        mock_batch = QuestionBatch(
            batch_index=0,
            questions=_make_batch_questions(3),
            status="generated",
        )
        with patch("app.core.generation_executor.generate_question_batch", new_callable=AsyncMock) as mock_gen:
            with patch("app.core.generation_executor.validate_question_batch") as mock_val:
                mock_gen.return_value = mock_batch
                mock_val.return_value = ValidationResult(is_valid=True)
                result = await _generate_single_batch(
                    plan=plan,
                    batch_index=0,
                    mode="resume",
                    temperature=0.7,
                    batch_size_override=None,
                    mode_config=_mode_config(),
                    semaphore=None,
                    should_terminate=lambda: False,
                    pause_event=None,
                )
        assert result.is_valid is True
        assert len(result.questions) == 3
        assert result.llm_calls_used == 1

    @pytest.mark.asyncio
    async def test_retry_after_validation_failure(self):
        """Single batch: fails validation first, succeeds on retry."""
        plan = _make_plan(total_batches=1, batch_size=3)
        mock_batch = QuestionBatch(
            batch_index=0,
            questions=_make_batch_questions(3),
            status="generated",
        )
        call_count = 0

        async def side_effect_gen(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_batch

        validation_results = [
            ValidationResult(is_valid=False, issues=["empty title"]),
            ValidationResult(is_valid=True),
        ]

        with patch("app.core.generation_executor.generate_question_batch", side_effect=side_effect_gen):
            with patch("app.core.generation_executor.validate_question_batch", side_effect=validation_results):
                result = await _generate_single_batch(
                    plan=plan,
                    batch_index=0,
                    mode="resume",
                    temperature=0.7,
                    batch_size_override=None,
                    mode_config=_mode_config({"max_validation_retries": 2}),
                    semaphore=None,
                    should_terminate=lambda: False,
                    pause_event=None,
                )
        assert result.is_valid is True
        assert result.llm_calls_used == 2  # First attempt + 1 retry


# ---------------------------------------------------------------------------
# Test execute_pass1
# ---------------------------------------------------------------------------

class TestExecutePass1:
    @pytest.mark.asyncio
    async def test_sequential_path(self):
        """execute_pass1 in sequential mode yields BatchResults in order."""
        plan = _make_plan(total_batches=2, batch_size=3, concurrency=1)
        mock_batch_0 = QuestionBatch(batch_index=0, questions=_make_batch_questions(3, 0), status="generated")
        mock_batch_1 = QuestionBatch(batch_index=1, questions=_make_batch_questions(3, 3), status="generated")

        batches = [mock_batch_0, mock_batch_1]

        async def gen_side_effect(*args, **kwargs):
            idx = kwargs.get("batch_index", 0)
            return batches[min(idx, len(batches) - 1)]

        results = []
        with patch("app.core.generation_executor.generate_question_batch", side_effect=gen_side_effect):
            with patch("app.core.generation_executor.validate_question_batch") as mock_val:
                mock_val.return_value = ValidationResult(is_valid=True)
                async for result in execute_pass1(
                    resume_plan=plan,
                    mode_config=_mode_config(),
                ):
                    results.append(result)

        assert len(results) == 2
        assert results[0].batch_index == 0
        assert results[1].batch_index == 1
        assert all(r.is_valid for r in results)

    @pytest.mark.asyncio
    async def test_terminate_early(self):
        """execute_pass1 should stop yielding when should_terminate returns True."""
        plan = _make_plan(total_batches=5, batch_size=3, concurrency=1)
        mock_batch = QuestionBatch(batch_index=0, questions=_make_batch_questions(3), status="generated")

        terminate_after = 2
        call_count = 0

        def should_terminate():
            nonlocal call_count
            return call_count >= terminate_after

        results = []
        with patch("app.core.generation_executor.generate_question_batch", new_callable=AsyncMock) as mock_gen:
            with patch("app.core.generation_executor.validate_question_batch") as mock_val:
                mock_gen.return_value = mock_batch
                mock_val.return_value = ValidationResult(is_valid=True)
                async for result in execute_pass1(
                    resume_plan=plan,
                    mode_config=_mode_config(),
                    should_terminate=should_terminate,
                ):
                    results.append(result)
                    call_count += 1

        assert len(results) <= 2


# ---------------------------------------------------------------------------
# Test execute_gap_fill
# ---------------------------------------------------------------------------

class TestExecuteGapFill:
    @pytest.mark.asyncio
    async def test_gap_fill_increments_until_target(self):
        """Gap-fill should continue yielding until target is met."""
        unique_start = [{"title": f"已有题 {i}"} for i in range(5)]
        target = 8  # Need 3 more

        mock_batch = QuestionBatch(
            batch_index=0,
            questions=[{"title": f"补充题 {i}"} for i in range(5)],
            status="generated",
        )

        results = []
        with patch("app.core.generation_executor.generate_question_batch", new_callable=AsyncMock) as mock_gen:
            with patch("app.core.generation_executor.validate_question_batch") as mock_val:
                mock_gen.return_value = mock_batch
                mock_val.return_value = ValidationResult(is_valid=True)
                async for result in execute_gap_fill(
                    unique_questions=unique_start,
                    target_count=target,
                    job_title="测试岗位",
                    jd_text="",
                    mode_config=_mode_config(),
                    max_total_attempts=50,
                    total_llm_calls_start=0,
                ):
                    results.append(result)

        # Should have gotten at least one supplement round that pushed unique count >= 8
        assert len(results) >= 1
        assert results[0].mode == "supplement"

    @pytest.mark.asyncio
    async def test_gap_fill_terminates_early(self):
        """Gap-fill should stop when should_terminate returns True."""
        unique_start = []  # Empty → need lots of supplement
        target = 100

        mock_batch = QuestionBatch(
            batch_index=0,
            questions=[{"title": f"补充题 {i}"} for i in range(5)],
            status="generated",
        )

        call_count = 0

        def should_terminate():
            nonlocal call_count
            return call_count >= 1

        results = []
        with patch("app.core.generation_executor.generate_question_batch", new_callable=AsyncMock) as mock_gen:
            with patch("app.core.generation_executor.validate_question_batch") as mock_val:
                mock_gen.return_value = mock_batch
                mock_val.return_value = ValidationResult(is_valid=True)
                async for result in execute_gap_fill(
                    unique_questions=unique_start,
                    target_count=target,
                    job_title="测试岗位",
                    jd_text="",
                    mode_config=_mode_config(),
                    max_total_attempts=500,
                    total_llm_calls_start=0,
                    should_terminate=should_terminate,
                ):
                    results.append(result)
                    call_count += 1

        assert len(results) <= 2  # At most 2 rounds before termination check kicks in


# ---------------------------------------------------------------------------
# Test config SSOT
# ---------------------------------------------------------------------------

class TestConfigSSOT:
    def test_constants_exist(self):
        assert MAX_QUESTION_COUNT == 100
        assert MAX_BATCH_SIZE == 15
        assert MAX_GENERATION_MULTIPLIER == 5
        assert MAX_SUPPLEMENT_ROUNDS == 10
        assert OVER_REQUEST_FACTOR == 1.3

    def test_resume_question_ratios(self):
        assert "full_resume" in RESUME_QUESTION_RATIOS
        assert "partial_resume" in RESUME_QUESTION_RATIOS
        assert "job_only" in RESUME_QUESTION_RATIOS
        assert RESUME_QUESTION_RATIOS["full_resume"] == 0.7
        assert RESUME_QUESTION_RATIOS["job_only"] == 0.0
