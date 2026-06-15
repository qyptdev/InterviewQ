"""Question generator service for resume-based question generation.

Orchestrates the full pipeline: document parsing -> resume extraction -> LLM generation -> bank storage.
"""

import asyncio
import logging
import math
from datetime import datetime
from typing import Optional, AsyncGenerator

from app.config import (
    MAX_QUESTION_COUNT,
    MAX_RESUME_FILE_SIZE,
    MAX_GENERATION_MULTIPLIER,
    MAX_SUPPLEMENT_ROUNDS,
    OVER_REQUEST_FACTOR,
    RESUME_QUESTION_RATIO,
    RESUME_QUESTION_RATIOS,
)
from app.core.graph_plan_execute import plan_and_execute, _resolve_resume_ratio
from app.core.state_models import QuestionPlan, QuestionBatch
from app.core.nodes_plan import analyze_resume, create_question_plan, _retrieve_rag_context
from app.core.nodes_execute import generate_question_batch
from app.core.generation_executor import (
    execute_pass1,
    execute_gap_fill,
    BatchResult,
)
from app.core.nodes_validate import validate_question_batch, deduplicate_questions, deduplicate_new_questions
from app.models.db_models import QuestionDAO, QuestionBankDAO, QuestionGenerationHistoryDAO
from app.services.document_parser import (
    parse_document,
    parse_document_binary,
    extract_resume_sections,
)
from app.services.generation_job import GenerationJob, generation_registry

logger = logging.getLogger(__name__)

# Supported file extensions for resume upload
RESUME_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}

# Binary file types (cannot decode as UTF-8)
BINARY_EXTENSIONS = {".pdf", ".docx"}


async def parse_uploaded_file(filename: str, content: bytes) -> str:
    """Parse an uploaded file and extract plain text.

    Args:
        filename: Original filename with extension.
        content: Raw file bytes.

    Returns:
        Extracted plain text content.

    Raises:
        ValueError: If file type is unsupported or parsing fails.
    """
    import os

    if not filename:
        raise ValueError("文件名不能为空")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in RESUME_EXTENSIONS:
        raise ValueError(f"不支持的文件格式: {ext}，支持: {', '.join(RESUME_EXTENSIONS)}")

    if len(content) > MAX_RESUME_FILE_SIZE:
        raise ValueError("文件大小超过限制 (10MB)")

    file_type = ext.lstrip(".")

    if ext in BINARY_EXTENSIONS:
        return parse_document_binary(content, file_type)
    else:
        # Text-based files: decode then parse
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text_content = content.decode("gbk")
            except UnicodeDecodeError:
                raise ValueError("无法解析文件编码，请使用 UTF-8 编码")

        return parse_document(text_content, file_type)


async def generate_questions_from_resume(
    resume_text: str,
    jd_text: str = "",
    job_title: str = "",
    question_count: int = 10,
    generation_mode: str = "standard",
) -> list[dict]:
    """Generate interview questions based on resume and optional JD.

    Uses the Plan-Execute pipeline to generate targeted questions.

    Args:
        resume_text: Parsed resume text.
        jd_text: Optional job description text.
        job_title: Target job title for question generation.
        question_count: Number of questions to generate (1-50).
        generation_mode: Generation mode ('fast', 'standard', 'deep').

    Returns:
        List of generated question dicts with title, category, difficulty, expected_answer.
    """
    if not resume_text.strip():
        raise ValueError("简历内容不能为空")

    question_count = max(1, min(question_count, MAX_QUESTION_COUNT))

    logger.info(
        f"Generating {question_count} questions from resume "
        f"(job_title={job_title}, resume_len={len(resume_text)}, jd_len={len(jd_text)}, mode={generation_mode})"
    )

    try:
        questions = await plan_and_execute(
            resume_text=resume_text,
            jd_text=jd_text,
            job_title=job_title,
            question_count=question_count,
            generation_mode=generation_mode,
        )

        logger.info(f"LLM generated {len(questions)} questions")
        return questions
    except Exception as e:
        logger.error(f"Question generation failed: {e}")
        raise ValueError(f"题目生成失败: {str(e)}")


def save_questions_to_bank(
    questions: list[dict],
    bank_name: Optional[str] = None,
) -> dict:
    """Save generated questions to a new question bank.

    Args:
        questions: List of question dicts from LLM generation.
        bank_name: Optional custom bank name. Defaults to auto-generated name.

    Returns:
        Dict with bank info and saved question count.
    """
    if not questions:
        raise ValueError("没有可保存的题目")

    # Auto-generate bank name if not provided
    if not bank_name:
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        bank_name = f"简历面试题-{date_str}"

    # Create the bank
    bank = QuestionBankDAO.create(
        name=bank_name,
        description=f"基于简历自动生成的面试题，共 {len(questions)} 题",
    )

    # Save each question and link to bank
    saved_ids = []
    for q in questions:
        title = q.get("title", "").strip()
        if not title:
            continue

        question = QuestionDAO.create(
            title=title,
            category=q.get("category", "简历面试"),
            difficulty=q.get("difficulty", "medium"),
            tags=q.get("tags", ""),
            expected_answer=q.get("expected_answer", ""),
        )
        saved_ids.append(question["id"])

    # Link questions to bank
    if saved_ids:
        QuestionBankDAO.add_questions(bank["id"], saved_ids)

    logger.info(f"Saved {len(saved_ids)} questions to bank '{bank_name}' (id={bank['id']})")

    return {
        "bank": bank,
        "questions_saved": len(saved_ids),
        "question_ids": saved_ids,
    }


async def process_resume_and_generate(
    filename: str,
    content: bytes,
    jd_text: str = "",
    job_title: str = "",
    question_count: int = 10,
    bank_name: Optional[str] = None,
    sections_override: Optional[dict] = None,
) -> dict:
    """Full pipeline: parse resume -> extract sections -> generate questions -> save to bank.

    Args:
        filename: Original filename.
        content: Raw file bytes.
        jd_text: Optional job description text.
        job_title: Target job title for question generation.
        question_count: Number of questions to generate.
        bank_name: Optional custom bank name.
        sections_override: Optional dict of user-edited resume sections.

    Returns:
        Dict with resume_sections, bank info, and generated questions.
    """
    # Step 1: Parse the uploaded file
    resume_text = await parse_uploaded_file(filename, content)

    if not resume_text.strip():
        raise ValueError("文件内容为空，无法提取文本")

    # Step 2: Extract resume sections (use override if provided)
    if sections_override:
        sections = sections_override
    else:
        sections = extract_resume_sections(resume_text)

    # Step 3: Generate questions via Plan-Execute pipeline
    questions = await generate_questions_from_resume(
        resume_text=resume_text,
        jd_text=jd_text,
        job_title=job_title,
        question_count=question_count,
    )

    # Step 4: Save to question bank
    result = save_questions_to_bank(questions, bank_name)

    return {
        "resume_sections": sections,
        "bank": result["bank"],
        "questions_saved": result["questions_saved"],
        "question_ids": result["question_ids"],
        "questions": questions,
    }


async def generate_questions_streaming(
    filename: str,
    content: bytes,
    jd_text: str = "",
    job_title: str = "",
    question_count: int = 10,
    bank_name: Optional[str] = None,
    sections_override: Optional[dict] = None,
    generation_mode: str = "standard",
    custom_batch_size: Optional[int] = None,
) -> AsyncGenerator[dict, None]:
    """Streaming version: generate questions one batch at a time, yield each as SSE event.

    Supports flexible input modes:
    - If filename and content are provided: parse resume and extract sections
    - If only job_title and jd_text are provided: generate based on job requirements
    - If both are provided: combine resume analysis with job requirements (recommended)

    Args:
        filename: Resume filename.
        content: Resume file content.
        jd_text: Job description text.
        job_title: Target job title.
        question_count: Number of questions to generate.
        bank_name: Optional custom bank name.
        sections_override: Optional user-edited resume sections.
        generation_mode: Generation mode ('fast', 'standard', 'deep').

    Yields:
        dict with keys:
          - type: "question" | "complete" | "error"
          - For "question": the single question dict
          - For "complete": {"bank_id", "bank_name", "questions_saved", "total_generated"}
          - For "error": {"message"}
    """
    from app.config import get_generation_mode_config

    mode_config = get_generation_mode_config(generation_mode)
    logger.info(f"Starting streaming generation with mode={generation_mode}")

    # Stage 1: Parsing
    yield {"type": "stage", "stage": "parsing", "message": "正在解析简历..."}

    # Step 1: Parse the uploaded file (if provided)
    resume_text = ""
    if filename and content:
        try:
            resume_text = await parse_uploaded_file(filename, content)
        except ValueError as e:
            yield {"type": "error", "message": f"简历解析失败: {str(e)}"}
            return

    # Step 2: Extract resume sections (use override if provided)
    if resume_text.strip():
        if sections_override:
            # Use user-edited sections (not used in generation, but could be for future features)
            pass
        else:
            # Extract sections for future use (currently not passed to generation)
            extract_resume_sections(resume_text)

    # Validate: at least resume or job_title must be provided
    if not resume_text.strip() and not job_title.strip():
        yield {"type": "error", "message": "请至少上传简历文件或填写岗位名称"}
        return

    # Stage 2: Analyzing
    # Step 3: Analyze resume (if provided)
    resume_summary = ""
    if resume_text.strip():
        analysis = await analyze_resume(resume_text)
        skills = analysis.get("skills", [])
        years = analysis.get("experience_years", 0)
        highlights = analysis.get("highlights", [])

        # Detect if analysis failed (empty result)
        analysis_failed = len(skills) == 0 and years == 0

        # Emit analyzing stage with details or fallback message
        if analysis_failed:
            yield {
                "type": "stage",
                "stage": "analyzing",
                "message": "简历分析未获取到信息，将基于岗位生成通用题目..."
            }
            logger.warning(
                f"Resume analysis returned empty result for resume "
                f"(length={len(resume_text)}). Will generate generic questions."
            )
        else:
            yield {
                "type": "stage",
                "stage": "analyzing",
                "message": f"正在分析简历（已识别 {len(skills)} 项技能，{years} 年经验）..."
            }

        meta = f"[分析] 技能: {', '.join(skills)} | 经验: {years}年"
        if highlights:
            meta += f" | 亮点: {'; '.join(str(h) for h in highlights)}"
        resume_summary = f"{meta}\n\n{resume_text}"
    elif job_title.strip():
        # No resume provided, use job title as context
        yield {
            "type": "stage",
            "stage": "analyzing",
            "message": f"基于岗位 {job_title} 准备生成题目..."
        }
        resume_summary = f"岗位: {job_title}"
        if jd_text.strip():
            resume_summary += f"\n\n{jd_text}"

    # Stage 3: Planning
    # Step 4: Calculate split (dynamic ratio based on input completeness)
    resume_ratio = _resolve_resume_ratio(resume_text, jd_text)
    resume_count = math.ceil(question_count * resume_ratio)

    # Retrieve RAG context from resume and JD (was missing — bug fix R1)
    rag_context = ""
    try:
        rag_context = await _retrieve_rag_context(
            resume_text=resume_text,
            jd_text=jd_text,
            job_title=job_title,
        ) or ""
        if rag_context:
            logger.info(f"Streaming RAG context retrieved: {len(rag_context)} chars")
    except Exception as e:
        logger.warning(f"Streaming RAG context retrieval failed (non-fatal): {e}")

    yield {
        "type": "stage",
        "stage": "planning",
        "message": f"正在规划题目类型（预计生成 {question_count} 题）..."
    }

    all_questions = []
    total_llm_calls = 0
    max_total_attempts = question_count * MAX_GENERATION_MULTIPLIER  # Safety limit
    effective_batch_size = custom_batch_size if custom_batch_size else None

    # === Pass 1: Resume-specific questions ===
    logger.info(f"Streaming Pass 1: Generating {resume_count} resume-specific questions")
    resume_plan = await create_question_plan(
        resume_summary=resume_summary,
        jd_requirements=jd_text,
        question_count=resume_count,
        job_title=job_title,
        rag_context=rag_context,
        custom_batch_size=custom_batch_size,
    )

    # Stage 4: Generating resume-specific questions
    for batch_idx in range(resume_plan.total_batches):
        yield {
            "type": "stage",
            "stage": "generating_resume",
            "message": f"正在生成简历相关题目（第 {batch_idx + 1}/{resume_plan.total_batches} 批）..."
        }

        batch = await generate_question_batch(
            plan=resume_plan,
            batch_index=batch_idx,
            topic=job_title,
            temperature=mode_config["temperature"],
            batch_size_override=effective_batch_size,
        )
        total_llm_calls += 1
        validation = validate_question_batch(batch)
        if validation.is_valid:
            for q in batch.questions:
                all_questions.append(q)
                yield {"type": "question", "question": q}
        else:
            logger.warning(f"Resume batch {batch_idx + 1} validation failed: {validation.issues}")
            max_validation_retries = mode_config.get("max_validation_retries", 2)
            if max_validation_retries > 1:
                batch = await generate_question_batch(
                    plan=resume_plan,
                    batch_index=batch_idx,
                    topic=job_title,
                    temperature=mode_config["temperature"],
                    batch_size_override=effective_batch_size,
                )
                total_llm_calls += 1
                validation = validate_question_batch(batch)
                if validation.is_valid:
                    for q in batch.questions:
                        all_questions.append(q)
                        yield {"type": "question", "question": q}

    # Dedup after Pass 1
    unique_so_far = deduplicate_questions(all_questions)
    logger.info(
        f"Streaming after Pass 1: {len(all_questions)} raw -> {len(unique_so_far)} unique "
        f"(target: {question_count})"
    )

    # === Pass 2 + Gap-fill loop: JD/general supplement ===
    supplement_round = 0
    while len(unique_so_far) < question_count and supplement_round < MAX_SUPPLEMENT_ROUNDS:
        needed = question_count - len(unique_so_far)
        request_count = min(
            math.ceil(needed * OVER_REQUEST_FACTOR),
            max_total_attempts - total_llm_calls,
        )
        if request_count <= 0:
            logger.warning(
                f"Streaming safety limit reached: total_llm_calls={total_llm_calls}, "
                f"max_allowed={max_total_attempts}. Stopping generation."
            )
            break

        supplement_round += 1

        # Stage 5: Supplementing
        yield {
            "type": "stage",
            "stage": "supplementing",
            "message": f"正在补充通用题目（第 {supplement_round} 轮，已有 {len(unique_so_far)} 题）..."
        }

        logger.info(
            f"Streaming supplement round {supplement_round}: need {needed} more, "
            f"requesting {request_count} (unique so far: {len(unique_so_far)})"
        )

        supplement_plan = QuestionPlan(
            job_title=job_title,
            resume_summary="",
            jd_requirements=jd_text,
            question_types=["岗位通用能力", "行业知识", "情景题"],
            total_batches=1,
            batch_size=request_count,
        )

        batch = await generate_question_batch(
            plan=supplement_plan,
            batch_index=0,
            topic=job_title,
            mode="supplement",
            temperature=mode_config["temperature"],
            batch_size_override=effective_batch_size,
        )
        total_llm_calls += 1
        validation = validate_question_batch(batch)

        # Collect new questions from this supplement round
        round_new_questions: list[dict] = []
        if validation.is_valid:
            round_new_questions = list(batch.questions)
            for q in round_new_questions:
                all_questions.append(q)
                yield {"type": "question", "question": q}
        else:
            logger.warning(
                f"Streaming supplement round {supplement_round} validation failed: {validation.issues}"
            )
            max_validation_retries = mode_config.get("max_validation_retries", 2)
            if max_validation_retries > 1:
                batch = await generate_question_batch(
                    plan=supplement_plan,
                    batch_index=0,
                    topic=job_title,
                    mode="supplement",
                    temperature=mode_config["temperature"],
                    batch_size_override=effective_batch_size,
                )
                total_llm_calls += 1
                validation = validate_question_batch(batch)
                if validation.is_valid:
                    round_new_questions = list(batch.questions)
                    for q in round_new_questions:
                        all_questions.append(q)
                        yield {"type": "question", "question": q}

        # Incremental dedup: only check new questions vs existing unique set
        if round_new_questions:
            unique_so_far = deduplicate_new_questions(
                new_questions=round_new_questions,
                existing_unique=unique_so_far,
            )
        logger.info(
            f"Streaming after supplement round {supplement_round}: "
            f"{len(unique_so_far)} unique (target: {question_count})"
        )

        if len(unique_so_far) >= question_count:
            break

    # === Final dedup + trim ===
    # Stage 6: Deduplicating
    yield {"type": "stage", "stage": "deduplicating", "message": "正在去重与质量检查..."}

    unique_questions = deduplicate_questions(all_questions)
    if len(unique_questions) > question_count:
        unique_questions = unique_questions[:question_count]

    # Stage 7: Saving
    yield {"type": "stage", "stage": "saving", "message": "正在保存至题库..."}

    # Step 5: Save to question bank
    try:
        result = save_questions_to_bank(unique_questions, bank_name)

        # Step 6: Save generation history
        generation_mode = "combined"
        if resume_text.strip() and not job_title.strip():
            generation_mode = "resume_only"
        elif not resume_text.strip() and job_title.strip():
            generation_mode = "job_only"

        try:
            QuestionGenerationHistoryDAO.create(
                job_title=job_title or "未指定岗位",
                question_count=result["questions_saved"],
                bank_id=result["bank"]["id"],
                bank_name=result["bank"]["name"],
                jd_text=jd_text,
                resume_filename=filename if filename else "",
                resume_text=resume_text if resume_text else "",
                generation_mode=generation_mode,
            )
            logger.info(f"Saved generation history for bank {result['bank']['id']}")
        except Exception as e:
            logger.warning(f"Failed to save generation history: {e}")

        yield {
            "type": "complete",
            "bank_id": result["bank"]["id"],
            "bank_name": result["bank"]["name"],
            "questions_saved": result["questions_saved"],
            "total_generated": len(unique_questions),
        }
    except ValueError as e:
        yield {"type": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Job-based generation: decoupled from request lifecycle
# ---------------------------------------------------------------------------


async def run_generation_job(
    job: GenerationJob,
    filename: str,
    content: bytes,
    jd_text: str = "",
    job_title: str = "",
    question_count: int = 10,
    bank_name: Optional[str] = None,
    sections_override: Optional[dict] = None,
    generation_mode: str = "standard",
    concurrency: int = 1,
    custom_batch_size: Optional[int] = None,
) -> None:
    """Run question generation as an independent asyncio task.

    Pushes all SSE events into ``job.event_queue`` so any connected client
    can consume them.  Accumulates questions in ``job.questions`` so that
    a terminate can persist partial results.
    """
    from app.config import get_generation_mode_config

    mode_config = get_generation_mode_config(generation_mode)
    job.status = "running"
    job.generation_params = {
        "generation_mode": generation_mode,
        "concurrency": concurrency,
        "custom_batch_size": custom_batch_size,
        "question_count": question_count,
    }

    def _emit(event: dict) -> None:
        job.push_event(event)

    try:
        # -- Parsing --
        job.current_stage = "parsing"
        _emit({"type": "stage", "stage": "parsing", "message": "正在解析简历..."})

        resume_text = ""
        if filename and content:
            try:
                resume_text = await parse_uploaded_file(filename, content)
            except ValueError as e:
                _emit({"type": "error", "message": f"简历解析失败: {str(e)}"})
                job.status = "error"
                job.error_message = str(e)
                return

        if resume_text.strip():
            if not sections_override:
                extract_resume_sections(resume_text)
        else:
            if not resume_text.strip() and not job_title.strip():
                _emit({"type": "error", "message": "请至少上传简历文件或填写岗位名称"})
                job.status = "error"
                job.error_message = "缺少输入"
                return

        # -- Analyzing --
        job.current_stage = "analyzing"
        resume_summary = ""
        if resume_text.strip():
            analysis = await analyze_resume(resume_text)
            skills = analysis.get("skills", [])
            years = analysis.get("experience_years", 0)
            highlights = analysis.get("highlights", [])

            analysis_failed = len(skills) == 0 and years == 0
            if analysis_failed:
                _emit({
                    "type": "stage",
                    "stage": "analyzing",
                    "message": "简历分析未获取到信息，将基于岗位生成通用题目...",
                })
                logger.warning(
                    f"Resume analysis returned empty result for resume "
                    f"(length={len(resume_text)}). Will generate generic questions."
                )
            else:
                _emit({
                    "type": "stage",
                    "stage": "analyzing",
                    "message": f"正在分析简历（已识别 {len(skills)} 项技能，{years} 年经验）...",
                })

            meta = f"[分析] 技能: {', '.join(skills)} | 经验: {years}年"
            if highlights:
                meta += f" | 亮点: {'; '.join(str(h) for h in highlights)}"
            resume_summary = f"{meta}\n\n{resume_text}"
        elif job_title.strip():
            _emit({
                "type": "stage",
                "stage": "analyzing",
                "message": f"基于岗位 {job_title} 准备生成题目...",
            })
            resume_summary = f"岗位: {job_title}"
            if jd_text.strip():
                resume_summary += f"\n\n{jd_text}"

        # -- Planning --
        job.current_stage = "planning"
        resume_ratio = _resolve_resume_ratio(resume_text, jd_text)
        resume_count = math.ceil(question_count * resume_ratio)
        _emit({
            "type": "stage",
            "stage": "planning",
            "message": f"正在规划题目类型（预计生成 {question_count} 题）...",
        })

        all_questions: list[dict] = []
        total_llm_calls = 0
        max_total_attempts = question_count * MAX_GENERATION_MULTIPLIER

        # -- Pass 1: Resume-specific questions (via generation_executor) --
        effective_batch_size = custom_batch_size if custom_batch_size else None
        logger.info(f"Job {job.job_id} Pass 1: Generating {resume_count} resume-specific questions")

        # Retrieve RAG context
        rag_context = ""
        try:
            rag_context = await _retrieve_rag_context(
                resume_text=resume_text,
                jd_text=jd_text,
                job_title=job_title,
            ) or ""
        except Exception as e:
            logger.warning(f"Job {job.job_id} RAG retrieval failed (non-fatal): {e}")

        resume_plan = await create_question_plan(
            resume_summary=resume_summary,
            jd_requirements=jd_text,
            question_count=resume_count,
            job_title=job_title,
            rag_context=rag_context,
            custom_batch_size=custom_batch_size,
            concurrency=concurrency,
        )

        # Emit stage events for Pass 1
        if concurrency > 1 and resume_plan.total_batches > 1:
            _emit({
                "type": "stage",
                "stage": "generating_resume",
                "message": f"正在并发生成简历相关题目（并发数={concurrency}，共 {resume_plan.total_batches} 批）...",
            })
        else:
            _emit({
                "type": "stage",
                "stage": "generating_resume",
                "message": f"正在生成简历相关题目（共 {resume_plan.total_batches} 批）...",
            })
        job.current_stage = "generating_resume"

        # Use unified executor
        async for batch_result in execute_pass1(
            resume_plan=resume_plan,
            mode_config=mode_config,
            batch_size_override=effective_batch_size,
            should_terminate=job.should_terminate,
            pause_event=job.pause_event,
        ):
            total_llm_calls += batch_result.llm_calls_used
            if batch_result.is_valid:
                for q in batch_result.questions:
                    all_questions.append(q)
                    job.questions.append(q)
                    job.completed_count = len(job.questions)
                    _emit({"type": "question", "question": q})
                    _emit({
                        "type": "progress_update",
                        "completed": job.completed_count,
                        "total": question_count,
                    })

        if job.should_terminate():
            # Skip further generation, go straight to save
            pass
        else:
            # Dedup after Pass 1
            unique_so_far = deduplicate_questions(all_questions)
            logger.info(
                f"Job {job.job_id} after Pass 1: {len(all_questions)} raw -> "
                f"{len(unique_so_far)} unique (target: {question_count})"
            )

            # -- Pass 2 + Gap-fill loop (via generation_executor) --
            async for batch_result in execute_gap_fill(
                unique_questions=unique_so_far,
                target_count=question_count,
                job_title=job_title,
                jd_text=jd_text,
                mode_config=mode_config,
                batch_size_override=effective_batch_size,
                max_total_attempts=max_total_attempts,
                total_llm_calls_start=total_llm_calls,
                should_terminate=job.should_terminate,
                pause_event=job.pause_event,
            ):
                total_llm_calls += batch_result.llm_calls_used
                supplement_round = getattr(batch_result, '_round', 0)
                job.current_stage = "supplementing"
                _emit({
                    "type": "stage",
                    "stage": "supplementing",
                    "message": f"正在补充通用题目（已有 {len(unique_so_far)} 题）...",
                })
                if batch_result.is_valid:
                    for q in batch_result.questions:
                        all_questions.append(q)
                        job.questions.append(q)
                        job.completed_count = len(job.questions)
                        _emit({"type": "question", "question": q})
                        _emit({
                            "type": "progress_update",
                            "completed": job.completed_count,
                            "total": question_count,
                        })
                    # Update unique_so_far for the loop condition
                    unique_so_far = deduplicate_new_questions(
                        new_questions=batch_result.questions,
                        existing_unique=unique_so_far,
                    )

        # -- Dedup + Save --
        job.current_stage = "deduplicating"
        _emit({"type": "stage", "stage": "deduplicating", "message": "正在去重与质量检查..."})

        unique_questions = deduplicate_questions(all_questions)
        if not job.should_terminate() and len(unique_questions) > question_count:
            unique_questions = unique_questions[:question_count]

        job.current_stage = "saving"
        _emit({"type": "stage", "stage": "saving", "message": "正在保存至题库..."})

        try:
            result = save_questions_to_bank(unique_questions, bank_name)
            job.bank_id = result["bank"]["id"]
            job.bank_name = result["bank"]["name"]

            # Save generation history
            gen_mode = "combined"
            if resume_text.strip() and not job_title.strip():
                gen_mode = "resume_only"
            elif not resume_text.strip() and job_title.strip():
                gen_mode = "job_only"

            try:
                QuestionGenerationHistoryDAO.create(
                    job_title=job_title or "未指定岗位",
                    question_count=result["questions_saved"],
                    bank_id=result["bank"]["id"],
                    bank_name=result["bank"]["name"],
                    jd_text=jd_text,
                    resume_filename=filename if filename else "",
                    resume_text=resume_text if resume_text else "",
                    generation_mode=gen_mode,
                )
            except Exception as e:
                logger.warning(f"Failed to save generation history: {e}")

            if job.should_terminate():
                job.status = "terminated"
                _emit({
                    "type": "complete",
                    "bank_id": result["bank"]["id"],
                    "bank_name": result["bank"]["name"],
                    "questions_saved": result["questions_saved"],
                    "total_generated": len(unique_questions),
                    "terminated_early": True,
                })
            else:
                job.status = "completed"
                _emit({
                    "type": "complete",
                    "bank_id": result["bank"]["id"],
                    "bank_name": result["bank"]["name"],
                    "questions_saved": result["questions_saved"],
                    "total_generated": len(unique_questions),
                })
        except ValueError as e:
            job.status = "error"
            job.error_message = str(e)
            _emit({"type": "error", "message": str(e)})

    except Exception as e:
        logger.error(f"Job {job.job_id} unexpected error: {e}", exc_info=True)
        job.status = "error"
        job.error_message = str(e)
        _emit({"type": "error", "message": f"生成失败: {str(e)}"})
    finally:
        generation_registry.schedule_cleanup(job.job_id)


async def stream_job_events(job: GenerationJob) -> AsyncGenerator[dict, None]:
    """Yield all past events and then stream new ones for a job.

    Used for reconnect: replays accumulated past_events first, then
    yields from the event_queue until the job is finished.

    After replaying past_events, the event_queue is drained to discard
    any events that were already recorded in past_events (prevents
    duplicate delivery on reconnect when the previous consumer
    disconnected mid-stream).
    """
    # Replay past events
    for event in job.past_events:
        yield event

    # If job is already done, nothing more to stream
    if job.status in ("completed", "terminated", "error"):
        return

    # Drain stale items from the queue — these are duplicates of
    # events we already replayed from past_events.
    while not job.event_queue.empty():
        try:
            job.event_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    # Stream only genuinely new events
    while True:
        try:
            event = await asyncio.wait_for(job.event_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            # Check if job finished while waiting
            if job.status in ("completed", "terminated", "error"):
                break
            continue
        yield event
        # If we got a complete or error event, stop
        if event.get("type") in ("complete", "error"):
            break


def create_generation_job(
    filename: str,
    content: bytes,
    jd_text: str = "",
    job_title: str = "",
    question_count: int = 10,
    bank_name: Optional[str] = None,
    sections_override: Optional[dict] = None,
    generation_mode: str = "standard",
    concurrency: int = 1,
    custom_batch_size: Optional[int] = None,
) -> GenerationJob:
    """Create a generation job and start it as a background asyncio task.

    Returns the job object; callers can then use ``job.job_id`` for
    reconnect/control endpoints.
    """
    job = generation_registry.create_job(bank_name=bank_name or "")
    job.total_planned = question_count

    job.task = asyncio.create_task(
        run_generation_job(
            job=job,
            filename=filename,
            content=content,
            jd_text=jd_text,
            job_title=job_title,
            question_count=question_count,
            bank_name=bank_name,
            sections_override=sections_override,
            generation_mode=generation_mode,
            concurrency=concurrency,
            custom_batch_size=custom_batch_size,
        )
    )
    return job

