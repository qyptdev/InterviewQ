"""LLM routing logic."""

import json
import logging
import re
from typing import AsyncGenerator, Optional

from app.llm.client import get_llm_router
from app.llm.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


async def generate_questions(
    category: str,
    difficulty: str,
    count: int,
    topic: str,
    language: str = "zh",
) -> list[dict]:
    """Generate interview questions using LLM."""
    router = get_llm_router()

    system_prompt = load_prompt(
        "generate_questions.txt",
        category=category,
        difficulty=difficulty,
        topic=topic,
        language=language,
    )

    user_prompt = f"请生成 {count} 道 {category} 方向的面试题"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response = await router.generate_with_fallback(
        messages,
        use_light=False,
        response_format={"type": "json_object"},
    )

    try:
        import json
        data = json.loads(response)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "questions" in data:
            return data["questions"]
        else:
            return [data]
    except json.JSONDecodeError:
        return [{"title": response, "expected_answer": ""}]


async def generate_interview_feedback(
    job_role: str,
    question_text: str,
    user_answer: str,
    question_index: int,
) -> dict:
    """Generate interview feedback using LLM."""
    router = get_llm_router()

    system_prompt = load_prompt(
        "interview_system.txt",
        job_role=job_role,
        question_index=question_index,
        question_text=question_text,
        user_answer=user_answer,
    )

    user_prompt = load_prompt("interview_user.txt")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response = await router.generate_with_fallback(
        messages,
        use_light=False,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(response)
        return {
            "feedback": data.get("feedback", "无法解析反馈"),
            "score": float(data.get("score", 50)),
        }
    except (json.JSONDecodeError, ValueError):
        return {"feedback": response, "score": 50.0}


async def generate_followup_question(
    job_role: str,
    question_text: str,
    user_answer: str,
    feedback_summary: str,
    score: float,
) -> Optional[str]:
    """Generate a follow-up question based on poor answer performance.

    Args:
        job_role: The job role being interviewed for.
        question_text: The original question text.
        user_answer: The candidate's answer.
        feedback_summary: Summary of AI feedback.
        score: The score received (should be < 60).

    Returns:
        Follow-up question text, or None if generation fails.
    """
    router = get_llm_router()

    try:
        system_prompt = load_prompt(
            "followup_question.txt",
            job_role=job_role,
            question_text=question_text,
            user_answer=user_answer,
            feedback_summary=feedback_summary,
            score=score,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "请生成追问。"},
        ]

        response = await router.generate_with_fallback(
            messages,
            use_light=True,  # Use lighter model for follow-ups to save cost
        )

        # Clean up response - strip whitespace and any accidental prefixes
        followup = response.strip()
        if not followup:
            logger.warning("Empty follow-up question generated")
            return None

        logger.info(f"Generated follow-up question for score {score}")
        return followup

    except Exception as e:
        logger.error(f"Follow-up question generation failed: {e}")
        return None


async def generate_interview_feedback_stream(
    job_role: str,
    question_text: str,
    user_answer: str,
    question_index: int,
) -> AsyncGenerator[dict, None]:
    """Generate interview feedback as a stream of chunks.

    Yields dicts with keys:
        - type: 'token' | 'done' | 'error'
        - content: str (token text or final JSON payload)
        - score: float (only in 'done' event)
    """
    router = get_llm_router()

    system_prompt = load_prompt(
        "interview_feedback_stream.txt",
        job_role=job_role,
        question_index=question_index,
        question_text=question_text,
        user_answer=user_answer,
    )

    user_prompt = "请给出你的反馈。"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    full_text = ""
    score = None  # Changed: Use None to detect if score was actually extracted
    score_pattern = re.compile(r"\[SCORE:(\d{1,3})\]")
    has_yielded_content = False

    try:
        async for chunk in router.generate_stream_with_fallback(messages):
            full_text += chunk

            # Check if this chunk contains the score marker(s)
            # Find all matches and extract the last one as the final score
            matches = list(score_pattern.finditer(chunk))
            if matches:
                # Use the last score if multiple are present
                last_match = matches[-1]
                try:
                    extracted_score = float(last_match.group(1))
                    # Only update score if valid (0-100)
                    if 0 <= extracted_score <= 100:
                        score = extracted_score
                        logger.info(f"Extracted score from stream: {score}")
                except ValueError:
                    logger.warning(f"Invalid score format in chunk: {last_match.group(1)}")

                # Remove ALL score markers from this chunk before yielding
                visible = score_pattern.sub("", chunk).strip()
                if visible:
                    yield {"type": "token", "content": visible}
                    has_yielded_content = True
            else:
                yield {"type": "token", "content": chunk}
                has_yielded_content = True

        # Clean up full text: remove ALL score markers from feedback body
        clean_feedback = score_pattern.sub("", full_text).strip()

        # Fallback: if no score extracted during streaming, try from full text
        # This handles cases where the marker was split across chunks
        if score is None:
            full_text_matches = list(score_pattern.finditer(full_text))
            if full_text_matches:
                try:
                    extracted = float(full_text_matches[-1].group(1))
                    if 0 <= extracted <= 100:
                        score = extracted
                        logger.info(f"Extracted score from full text fallback: {score}")
                except ValueError:
                    pass

        # Final score validation: use extracted score or default to 50 if none found
        final_score = score if score is not None else 50.0

        if final_score == 50.0 and score is None:
            logger.warning(f"No valid score found in feedback, using default: {final_score}")

        # Only yield done event if we actually have content
        if clean_feedback or has_yielded_content:
            yield {
                "type": "done",
                "content": clean_feedback,
                "score": final_score,
            }
        else:
            # No content generated - treat as error
            yield {
                "type": "error",
                "content": "AI 未生成有效反馈，请重试",
                "score": 0.0,
            }
    except Exception as e:
        logger.error(f"Streaming feedback generation failed: {e}")
        # If we've already yielded some content, preserve extracted score
        if has_yielded_content and full_text.strip():
            clean_feedback = score_pattern.sub("", full_text).strip()
            # Use extracted score if available, otherwise default to 50
            final_score = score if score is not None else 50.0
            logger.warning(f"Exception during stream, using score: {final_score}")
            yield {
                "type": "done",
                "content": clean_feedback,
                "score": final_score,
            }
        else:
            yield {
                "type": "error",
                "content": "无法生成反馈，请稍后重试",
                "score": 0.0,
            }
