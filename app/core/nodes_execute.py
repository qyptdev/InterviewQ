"""Execute node for question generation."""

import json
import logging
import re

from app.config import MAX_BATCH_SIZE, MAX_LLM_UNDERPRODUCE_RETRIES, LLM_MAX_TOKENS_GENERATION
from app.core.state_models import QuestionPlan, QuestionBatch
from app.llm.client import get_llm_router
from app.llm.prompt_loader import load_prompt

logger = logging.getLogger(__name__)



def _extract_json_from_response(text: str, log_prefix: str = "") -> dict | list | None:
    """Extract JSON from LLM response, handling markdown code blocks and malformed JSON."""
    _pfx = f"[{log_prefix}] " if log_prefix else ""
    if not text or not text.strip():
        logger.debug(f"{_pfx}JSON extract: empty input")
        return None

    text = text.strip()

    # Try to extract JSON from markdown code blocks first
    code_block_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if code_block_match:
        text = code_block_match.group(1).strip()
        logger.debug(f"{_pfx}JSON extract stage=code_block len={len(text)}")
    else:
        logger.debug(f"{_pfx}JSON extract stage=raw_text len={len(text)}")

    # Try direct JSON parse
    try:
        result = json.loads(text)
        logger.debug(f"{_pfx}JSON extract stage=direct success")
        return result
    except json.JSONDecodeError as e:
        logger.debug(f"{_pfx}JSON extract stage=direct failed: {e}")

    # Try to find JSON array or object in the text
    for pattern in [r'\[[\s\S]*\]', r'\{[\s\S]*\}']:
        match = re.search(pattern, text)
        if match:
            try:
                result = json.loads(match.group())
                logger.debug(f"{_pfx}JSON extract stage=regex_{pattern[:6]} success")
                return result
            except json.JSONDecodeError as e:
                logger.debug(f"{_pfx}JSON extract stage=regex_{pattern[:6]} failed: {e}")
                continue

    # Try to repair truncated JSON (common when response is cut off)
    # Case 1: Array that was cut off — find the last complete object
    if text.startswith('['):
        last_complete = _find_last_complete_json_object(text)
        if last_complete:
            try:
                result = json.loads(last_complete + ']')
                logger.debug(f"{_pfx}JSON extract stage=truncation_repair success len={len(result) if isinstance(result, list) else '?'}")
                return result
            except json.JSONDecodeError as e:
                logger.debug(f"{_pfx}JSON extract stage=truncation_repair failed: {e}")

    # Case 2: Single truncated object — try to close it
    if text.startswith('{') and not text.endswith('}'):
        repaired = _try_close_truncated_object(text)
        if repaired:
            try:
                result = json.loads(repaired)
                # Wrap single object into a list for uniform downstream handling
                if isinstance(result, dict):
                    result = [result]
                logger.debug(f"{_pfx}JSON extract stage=single_obj_repair success")
                return result
            except json.JSONDecodeError as e:
                logger.debug(f"{_pfx}JSON extract stage=single_obj_repair failed: {e}")

    # Case 3: Single complete object (not in an array) — wrap into list
    if text.startswith('{') and text.endswith('}'):
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                # Check if it looks like a single question or a wrapper with "questions" key
                if "questions" in result and isinstance(result["questions"], list):
                    return result["questions"]
                elif "title" in result or "question" in result:
                    return [result]
                else:
                    return [result]
        except json.JSONDecodeError:
            pass

    logger.debug(f"{_pfx}JSON extract FAILED all stages, raw[:500]= {text[:500]!r}")
    return None


def _find_last_complete_json_object(text: str) -> str | None:
    """Find the last complete JSON object in a potentially truncated array."""
    # Remove the opening bracket
    if not text.startswith('['):
        return None

    text = text[1:]  # Remove [
    depth = 0
    last_complete_end = -1
    in_string = False
    escape_next = False

    for i, char in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if char == '\\' and in_string:
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue

        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                last_complete_end = i + 1
        elif char == ']' and depth == 0:
            break

    if last_complete_end > 0:
        return '[' + text[:last_complete_end]
    return None


def _try_close_truncated_object(text: str) -> str | None:
    """Attempt to close a truncated JSON object by counting brace depth.

    Handles cases where LLM returns a single question object that gets
    cut off mid-value (e.g., long expected_answer). Adds closing quotes
    and braces as needed.
    """
    if not text.startswith('{'):
        return None

    depth = 0
    in_string = False
    escape_next = False
    last_valid_pos = len(text)

    for i, char in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if char == '\\' and in_string:
            escape_next = True
            continue
        if char == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue

        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                # Already complete
                return text
        elif char == ':':
            last_valid_pos = i

    # Build closing suffix
    suffix = ""
    if in_string:
        suffix += '"'
    # Close open braces
    suffix += '}' * depth

    result = text + suffix
    # Validate the result is parseable
    try:
        json.loads(result)
        return result
    except json.JSONDecodeError:
        return None


async def generate_question_batch(
    plan: QuestionPlan,
    batch_index: int,
    topic: str = "",
    mode: str = "resume",
    temperature: float = None,
    batch_size_override: int | None = None,
) -> QuestionBatch:
    """Generate a batch of questions based on the plan.

    Args:
        plan: The question generation plan with context (job_title, resume, JD).
        batch_index: Index of the current batch.
        topic: Legacy topic parameter (overridden by plan.job_title if set).
        mode: "resume" for resume-specific questions, "supplement" for JD/general questions.
        temperature: Optional temperature override for LLM generation.
        batch_size_override: Optional custom batch size from user params. Bounded
            to ``[1, MAX_BATCH_SIZE]`` before use.

    Returns:
        QuestionBatch with generated questions.
    """
    router = get_llm_router()

    q_type = plan.question_types[batch_index % len(plan.question_types)] if plan.question_types else "通用"

    if mode == "supplement":
        messages, target_text = _build_supplement_messages(plan, q_type)
    else:
        messages, target_text = _build_resume_messages(plan, q_type)

    all_questions = []
    retries = 0
    target_count = plan.batch_size
    # Cap batch size to avoid LLM response truncation
    if batch_size_override is not None:
        effective_batch_size = max(1, min(batch_size_override, MAX_BATCH_SIZE))
        logger.info(f"Using user-provided batch_size={effective_batch_size} (raw={batch_size_override})")
    else:
        effective_batch_size = min(target_count, MAX_BATCH_SIZE)

    while len(all_questions) < target_count and retries < MAX_LLM_UNDERPRODUCE_RETRIES:
        remaining = target_count - len(all_questions)
        request_count = min(remaining, effective_batch_size)
        # Update the user prompt to request the exact remaining count
        if mode == "supplement":
            messages[1]["content"] = f"请生成 {request_count} 道岗位通用面试题，作为简历项目题的补充。"
        else:
            messages[1]["content"] = f"请生成 {request_count} 道高质量面试题，{target_text}"

        try:
            response = await router.generate_with_fallback(
                messages,
                use_light=False,
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=LLM_MAX_TOKENS_GENERATION,
            )

            # Parse JSON with robust extraction
            log_prefix = f"Batch{batch_index + 1}-R{retries}"
            data = _extract_json_from_response(response, log_prefix=log_prefix)
            if data is None:
                logger.error(
                    f"Failed to extract valid JSON from response "
                    f"(batch={batch_index + 1} mode={mode} retry={retries}), "
                    f"raw[:300]={response[:300]!r}"
                )
                continue

            questions = data if isinstance(data, list) else data.get("questions", [data])
            if not isinstance(questions, list):
                questions = [questions]

            # Filter out empty/invalid questions
            # Accept common field name variants: title, question, topic, name
            valid = []
            for q in questions:
                if not isinstance(q, dict):
                    continue
                title = (
                    q.get("title", "")
                    or q.get("question", "")
                    or q.get("topic", "")
                    or q.get("name", "")
                )
                if isinstance(title, list):
                    title = " ".join(str(t) for t in title).strip()
                if title and len(str(title).strip()) > 5:
                    # Normalize to "title" field for downstream consumers
                    normalized_title = str(title).strip()
                    q["title"] = normalized_title
                    valid.append(q)

            all_questions.extend(valid)
            logger.info(
                f"Batch {batch_index + 1} (mode={mode}) retry={retries}: "
                f"got {len(valid)} valid questions, total so far={len(all_questions)}/{target_count}"
            )
        except Exception as e:
            logger.error(f"Question batch generation failed (retry={retries}): {e}")

        retries += 1

    # Trim to exact target count
    questions = all_questions[:target_count]

    return QuestionBatch(
        batch_index=batch_index,
        questions=questions,
        status="generated" if questions else "failed",
    )


def _build_resume_messages(plan: QuestionPlan, q_type: str) -> tuple:
    """Build messages for resume-mode question generation."""
    context_parts = []
    if plan.job_title:
        context_parts.append(f"目标岗位：{plan.job_title}")
    if plan.jd_requirements:
        context_parts.append(f"岗位要求：{plan.jd_requirements}")

    context_str = "\n".join(context_parts) if context_parts else "无特定背景信息"

    # Append RAG context if available
    resume_with_rag = plan.resume_summary
    if plan.rag_context:
        resume_with_rag = (
            f"{plan.resume_summary}\n\n"
            f"=== RAG 检索到的相关片段 ===\n{plan.rag_context}\n=== END RAG ==="
        )

    system_prompt = load_prompt(
        "question_batch_resume.txt",
        job_title=plan.job_title or '目标岗位',
        context_str=context_str,
        resume_summary=resume_with_rag,
        q_type=q_type,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": ""},
    ]

    return messages, "重点围绕候选人的项目经历和岗位要求。"


def _build_supplement_messages(plan: QuestionPlan, q_type: str) -> tuple:
    """Build messages for supplement-mode question generation."""
    system_prompt = load_prompt(
        "question_batch_supplement.txt",
        job_title=plan.job_title or '目标岗位',
        jd_requirements=plan.jd_requirements or '无',
        q_type=q_type,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": ""},
    ]

    return messages, "岗位通用面试题，作为简历项目题的补充。"
