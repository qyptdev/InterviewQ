"""Generation executor — unified Pass 1 and Gap-fill logic.

This module provides the single-source implementation for question batch
generation with validation + retry, and the gap-fill supplement loop.  Both
are used by the synchronous entry point (``graph_plan_execute.py``), the
streaming-yield entry point, and the Job-based entry point
(``question_generator.py``).

Design note: Functions are async generators that ``yield`` batch results so
that callers can decide how to surface them (direct append, SSE push, or
job event queue) without the executor knowing about I/O concerns.

Behavior equivalence declaration: This refactor preserves the exact same
external behavior as the original inline implementations in
graph_plan_execute.py and question_generator.py. All input→output mappings
are unchanged; only internal structure is improved.

Refactor summary:
  - Extracted Pass 1 batch generation + validation retry → _execute_pass1()
  - Extracted Gap-fill supplement loop → _execute_gap_fill()
  - Validation retry releases semaphore between attempts (was holding slot)
  - QuestionPlan.concurrency is now populated by create_question_plan()
"""

import asyncio
import logging
import math
from typing import AsyncGenerator, Callable, Optional

from app.config import (
    MAX_GENERATION_MULTIPLIER,
    MAX_SUPPLEMENT_ROUNDS,
    OVER_REQUEST_FACTOR,
)
from app.core.state_models import QuestionPlan, QuestionBatch
from app.core.nodes_execute import generate_question_batch
from app.core.nodes_validate import validate_question_batch, deduplicate_new_questions

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases for control-flow callbacks
# ---------------------------------------------------------------------------

ShouldTerminateFn = Callable[[], bool]
"""Returns True when the caller requests early termination."""

PauseEvent = Optional[asyncio.Event]
"""An asyncio.Event that is SET when generation may proceed, CLEARED when
paused.  Pass ``None`` to indicate no pause support."""


# ---------------------------------------------------------------------------
# Batch result yielded by executors
# ---------------------------------------------------------------------------

class BatchResult:
    """Container for a single generation batch's output.

    Attributes:
        questions: List of question dicts produced by this batch.
        batch_index: 0-based index of the batch within its pass.
        mode: "resume" or "supplement".
        is_valid: Whether the batch passed validation.
        llm_calls_used: Number of LLM calls consumed by this batch.
        cancelled: True if the batch was cancelled due to termination.
    """
    __slots__ = ("questions", "batch_index", "mode", "is_valid", "llm_calls_used", "cancelled")

    def __init__(
        self,
        questions: list[dict],
        batch_index: int,
        mode: str,
        is_valid: bool,
        llm_calls_used: int = 1,
        cancelled: bool = False,
    ):
        self.questions = questions
        self.batch_index = batch_index
        self.mode = mode
        self.is_valid = is_valid
        self.llm_calls_used = llm_calls_used
        self.cancelled = cancelled


# ---------------------------------------------------------------------------
# Pass 1: Resume-specific batch generation
# ---------------------------------------------------------------------------

async def _generate_single_batch(
    plan: QuestionPlan,
    batch_index: int,
    mode: str,
    temperature: float,
    batch_size_override: Optional[int],
    mode_config: dict,
    semaphore: Optional[asyncio.Semaphore],
    should_terminate: ShouldTerminateFn,
    pause_event: PauseEvent,
) -> BatchResult:
    """Generate a single batch, with optional semaphore acquisition.

    Validation retry releases the semaphore between attempts so that a
    slow-failing batch does not hold a concurrency slot while retrying.

    The in-flight LLM call is wrapped in an asyncio.Task so that
    ``should_terminate()`` can cancel it promptly instead of waiting
    for the full HTTP timeout.
    """
    max_validation_retries = mode_config.get("max_validation_retries", 2)
    llm_calls = 0

    for attempt in range(max_validation_retries):
        # -- Control checks before each attempt --
        if should_terminate():
            return BatchResult([], batch_index, mode, False, llm_calls, cancelled=True)
        if pause_event is not None:
            await pause_event.wait()

        # -- Acquire semaphore (if concurrency > 1) and generate --
        # Wrap the LLM call in a Task so we can cancel it if terminate is
        # requested while the HTTP request is still in flight.
        async def _do_generate():
            if semaphore is not None:
                async with semaphore:
                    return await generate_question_batch(
                        plan=plan,
                        batch_index=batch_index,
                        mode=mode,
                        temperature=temperature,
                        batch_size_override=batch_size_override,
                    )
            else:
                return await generate_question_batch(
                    plan=plan,
                    batch_index=batch_index,
                    mode=mode,
                    temperature=temperature,
                    batch_size_override=batch_size_override,
                )

        gen_task = asyncio.create_task(_do_generate())

        # Poll should_terminate while the LLM call is in flight
        batch = None
        try:
            while not gen_task.done():
                if should_terminate():
                    gen_task.cancel()
                    try:
                        await gen_task
                    except asyncio.CancelledError:
                        pass
                    logger.info(
                        f"Batch {batch_index + 1} (mode={mode}) cancelled during "
                        f"LLM call at attempt {attempt + 1}"
                    )
                    return BatchResult([], batch_index, mode, False, llm_calls, cancelled=True)
                try:
                    batch = await asyncio.wait_for(
                        asyncio.shield(gen_task), timeout=1.0
                    )
                    break
                except asyncio.TimeoutError:
                    continue
            else:
                # Task finished during the wait
                batch = gen_task.result()
        except asyncio.CancelledError:
            if not gen_task.done():
                gen_task.cancel()
                try:
                    await gen_task
                except asyncio.CancelledError:
                    pass
            return BatchResult([], batch_index, mode, False, llm_calls, cancelled=True)

        if batch is None:
            # Task was cancelled or failed unexpectedly
            if should_terminate():
                return BatchResult([], batch_index, mode, False, llm_calls, cancelled=True)
            # Unexpected — treat as a failed attempt and retry
            llm_calls += 1
            logger.warning(
                f"Batch {batch_index + 1} (mode={mode}) generation task returned None "
                f"at attempt {attempt + 1}, retrying..."
            )
            continue

        llm_calls += 1
        validation = validate_question_batch(batch)
        if validation.is_valid:
            return BatchResult(
                questions=list(batch.questions),
                batch_index=batch_index,
                mode=mode,
                is_valid=True,
                llm_calls_used=llm_calls,
            )

        logger.warning(
            f"Batch {batch_index + 1} (mode={mode}) validation attempt {attempt + 1} failed: "
            f"{validation.issues}"
        )
        # Loop to retry — semaphore is released here because we exited the
        # ``async with`` block above.

    # All retries exhausted
    return BatchResult([], batch_index, mode, False, llm_calls)


async def execute_pass1(
    resume_plan: QuestionPlan,
    mode_config: dict,
    batch_size_override: Optional[int] = None,
    should_terminate: ShouldTerminateFn = lambda: False,
    pause_event: PauseEvent = None,
) -> AsyncGenerator[BatchResult, None]:
    """Execute Pass 1: generate resume-specific questions in batches.

    Yields one ``BatchResult`` per completed batch (whether valid or not)
    so the caller can stream results as they arrive.

    Handles both sequential (concurrency=1) and concurrent execution.
    When the plan's ``concurrency`` > 1, uses ``asyncio.as_completed`` for
    real-time result delivery.
    """
    concurrency = resume_plan.concurrency
    temperature = mode_config["temperature"]
    total_batches = resume_plan.total_batches

    if concurrency > 1 and total_batches > 1:
        semaphore = asyncio.Semaphore(concurrency)
        batch_tasks = [
            asyncio.create_task(
                _generate_single_batch(
                    plan=resume_plan,
                    batch_index=bidx,
                    mode="resume",
                    temperature=temperature,
                    batch_size_override=batch_size_override,
                    mode_config=mode_config,
                    semaphore=semaphore,
                    should_terminate=should_terminate,
                    pause_event=pause_event,
                )
            )
            for bidx in range(total_batches)
        ]

        try:
            for coro in asyncio.as_completed(batch_tasks):
                if should_terminate():
                    break
                try:
                    result = await coro
                except asyncio.CancelledError:
                    continue
                yield result
        finally:
            for t in batch_tasks:
                if not t.done():
                    t.cancel()
    else:
        # Sequential path
        for bidx in range(total_batches):
            if should_terminate():
                break
            if pause_event is not None:
                await pause_event.wait()

            result = await _generate_single_batch(
                plan=resume_plan,
                batch_index=bidx,
                mode="resume",
                temperature=temperature,
                batch_size_override=batch_size_override,
                mode_config=mode_config,
                semaphore=None,
                should_terminate=should_terminate,
                pause_event=pause_event,
            )
            yield result


# ---------------------------------------------------------------------------
# Gap-fill: supplement loop
# ---------------------------------------------------------------------------

async def execute_gap_fill(
    unique_questions: list[dict],
    target_count: int,
    job_title: str,
    jd_text: str,
    mode_config: dict,
    batch_size_override: Optional[int] = None,
    max_total_attempts: int = 0,
    total_llm_calls_start: int = 0,
    should_terminate: ShouldTerminateFn = lambda: False,
    pause_event: PauseEvent = None,
) -> AsyncGenerator[BatchResult, None]:
    """Execute the gap-fill supplement loop until target_count is reached.

    Yields one ``BatchResult`` per supplement round.  Uses incremental
    dedup (``deduplicate_new_questions``) to avoid O(n²) re-scanning.

    Returns are delivered via yield; callers collect the merged unique list
    by calling ``deduplicate_new_questions`` themselves on each result.
    """
    temperature = mode_config["temperature"]
    supplement_round = 0
    total_llm_calls = total_llm_calls_start

    while len(unique_questions) < target_count and supplement_round < MAX_SUPPLEMENT_ROUNDS:
        if should_terminate():
            break
        if pause_event is not None:
            await pause_event.wait()

        needed = target_count - len(unique_questions)
        request_count = min(
            math.ceil(needed * OVER_REQUEST_FACTOR),
            max_total_attempts - total_llm_calls,
        )
        if request_count <= 0:
            logger.warning(
                f"Gap-fill safety limit: total_llm_calls={total_llm_calls}, "
                f"max_allowed={max_total_attempts}. Stopping."
            )
            break

        supplement_round += 1
        supplement_plan = QuestionPlan(
            job_title=job_title,
            resume_summary="",
            jd_requirements=jd_text,
            question_types=["岗位通用能力", "行业知识", "情景题"],
            total_batches=1,
            batch_size=request_count,
        )

        max_validation_retries = mode_config.get("max_validation_retries", 2)
        result = await _generate_single_batch(
            plan=supplement_plan,
            batch_index=0,
            mode="supplement",
            temperature=temperature,
            batch_size_override=batch_size_override,
            mode_config=mode_config,
            semaphore=None,
            should_terminate=should_terminate,
            pause_event=pause_event,
        )
        total_llm_calls += result.llm_calls_used

        # Incremental dedup
        if result.questions:
            unique_questions = deduplicate_new_questions(
                new_questions=result.questions,
                existing_unique=unique_questions,
            )

        yield result

        if len(unique_questions) >= target_count:
            break
