"""Graph for Plan-Execute question generation.

Orchestrates the full pipeline: analyze resume → plan → generate → dedup → gap-fill.

This module serves as the synchronous (non-streaming, non-Job) entry point.
It delegates batch generation and gap-fill to ``generation_executor.py``.
"""

import asyncio
import logging
import math

from app.config import (
    MAX_GENERATION_MULTIPLIER,
    RESUME_QUESTION_RATIOS,
)
from app.core.state_models import QuestionPlan, QuestionBatch
from app.core.nodes_plan import analyze_resume, create_question_plan, _retrieve_rag_context
from app.core.nodes_execute import generate_question_batch
from app.core.nodes_validate import validate_question_batch, deduplicate_questions, deduplicate_new_questions
from app.core.generation_executor import (
    execute_pass1,
    execute_gap_fill,
    BatchResult,
)

logger = logging.getLogger(__name__)


def _resolve_resume_ratio(resume_text: str, jd_text: str) -> float:
    """Determine the resume-question ratio based on input completeness.

    If a substantive resume is provided, most questions should be resume-specific.
    If only JD/job-title is available, all questions go to supplement.

    Args:
        resume_text: Parsed resume text (may be empty).
        jd_text: Job description text (may be empty).

    Returns:
        Ratio of resume-specific questions (0.0 – 0.7).
    """
    stripped_resume = resume_text.strip() if resume_text else ""
    has_substantive_resume = len(stripped_resume) > 200
    has_any_resume = len(stripped_resume) > 0

    if has_substantive_resume:
        return RESUME_QUESTION_RATIOS["full_resume"]
    elif has_any_resume:
        return RESUME_QUESTION_RATIOS["partial_resume"]
    else:
        return RESUME_QUESTION_RATIOS["job_only"]


async def plan_and_execute(
    resume_text: str = "",
    jd_text: str = "",
    job_title: str = "",
    question_count: int = 10,
    generation_mode: str = "standard",
    concurrency: int = 1,
    custom_batch_size: int | None = None,
) -> list[dict]:
    """Execute the Plan-Execute pipeline for question generation.

    Multi-pass strategy with gap-filling:
    - Pass 1: Generate resume-specific questions (project deep-dive, work experience)
    - Pass 2: Supplement with JD/job-title-based general questions if not enough
    - Gap-fill loop: Continue generating supplement batches until target is met
      or safety limits are reached

    Args:
        resume_text: Full resume text.
        jd_text: Job description text.
        job_title: Target job title for question generation.
        question_count: Number of questions to generate.
        generation_mode: Generation mode ('fast', 'standard', 'deep').
        concurrency: Max concurrent batch generation (1 = sequential, no regression).
        custom_batch_size: Optional user-specified batch size override.

    Returns:
        List of unique generated question dicts.
    """
    from app.config import get_generation_mode_config

    mode_config = get_generation_mode_config(generation_mode)
    logger.info(
        f"Question generation started: target={question_count}, mode={generation_mode}, "
        f"concurrency={concurrency}, custom_batch_size={custom_batch_size}, "
        f"resume_len={len(resume_text)}, jd_len={len(jd_text)}, job_title='{job_title}'"
    )

    # Step 1: Build detailed resume summary (preserve project details)
    resume_summary = resume_text
    if resume_text:
        analysis = await analyze_resume(resume_text)
        skills = analysis.get("skills", [])
        years = analysis.get("experience_years", 0)
        highlights = analysis.get("highlights", [])
        meta = f"[分析] 技能: {', '.join(skills)} | 经验: {years}年"
        if highlights:
            meta += f" | 亮点: {'; '.join(str(h) for h in highlights)}"
        resume_summary = f"{meta}\n\n{resume_text}"

    # Step 1.5: Retrieve RAG context from resume and JD
    rag_context = await _retrieve_rag_context(
        resume_text=resume_text,
        jd_text=jd_text,
        job_title=job_title,
    )
    if rag_context:
        logger.info(f"RAG context retrieved: {len(rag_context)} chars")
    else:
        logger.info("No RAG context available, proceeding without RAG")

    # Calculate split: resume questions vs JD/general supplement
    resume_ratio = _resolve_resume_ratio(resume_text, jd_text)
    resume_count = math.ceil(question_count * resume_ratio)
    supplement_count = question_count - resume_count

    all_questions: list[dict] = []
    total_llm_calls = 0
    max_total_attempts = question_count * MAX_GENERATION_MULTIPLIER

    # === Pass 1: Resume-specific questions (via generation_executor) ===
    logger.info(f"Pass 1: Generating {resume_count} resume-specific questions")
    resume_plan = await create_question_plan(
        resume_summary=resume_summary,
        jd_requirements=jd_text,
        question_count=resume_count,
        job_title=job_title,
        rag_context=rag_context,
        custom_batch_size=custom_batch_size,
        concurrency=concurrency,
    )

    # Collect Pass 1 results from the executor
    async for batch_result in execute_pass1(
        resume_plan=resume_plan,
        mode_config=mode_config,
        batch_size_override=custom_batch_size,
    ):
        total_llm_calls += batch_result.llm_calls_used
        if batch_result.is_valid:
            all_questions.extend(batch_result.questions)
            logger.info(
                f"Resume batch {batch_result.batch_index + 1}/{resume_plan.total_batches}: "
                f"{len(batch_result.questions)} questions (total so far: {len(all_questions)})"
            )

    # Dedup after Pass 1
    unique_after_pass1 = deduplicate_questions(all_questions)
    logger.info(
        f"After Pass 1: {len(all_questions)} raw -> {len(unique_after_pass1)} unique "
        f"(target: {question_count})"
    )

    # === Pass 2 + Gap-fill loop (via generation_executor) ===
    async for batch_result in execute_gap_fill(
        unique_questions=unique_after_pass1,
        target_count=question_count,
        job_title=job_title,
        jd_text=jd_text,
        mode_config=mode_config,
        batch_size_override=custom_batch_size,
        max_total_attempts=max_total_attempts,
        total_llm_calls_start=total_llm_calls,
    ):
        total_llm_calls += batch_result.llm_calls_used
        # The executor already did incremental dedup internally;
        # but we also extend all_questions for the final dedup
        if batch_result.is_valid:
            all_questions.extend(batch_result.questions)

    # === Final dedup ===
    unique_questions = deduplicate_questions(all_questions)

    # Trim to requested count
    if len(unique_questions) > question_count:
        unique_questions = unique_questions[:question_count]

    logger.info(
        f"Question generation complete: {len(unique_questions)}/{question_count} unique questions "
        f"from {len(all_questions)} total raw, {total_llm_calls} LLM calls"
    )
    return unique_questions
