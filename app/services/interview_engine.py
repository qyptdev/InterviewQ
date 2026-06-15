"""Interview engine for managing interview sessions."""

import logging
from typing import AsyncGenerator, Optional

from app.models.db_models import SessionDAO, InterviewQuestionDAO, QuestionDAO
from app.llm.router import (
    generate_interview_feedback,
    generate_interview_feedback_stream,
    generate_followup_question,
)

logger = logging.getLogger(__name__)


class InterviewEngine:
    """Engine for managing interview sessions."""

    @staticmethod
    def create_session(title: str, job_role: str = "") -> dict:
        """Create a new interview session."""
        return SessionDAO.create(title, job_role)

    @staticmethod
    def get_session(session_id: int) -> Optional[dict]:
        """Get a session by ID."""
        return SessionDAO.get_by_id(session_id)

    @staticmethod
    def list_sessions(
        status: Optional[str] = None, page: int = 1, page_size: int = 20
    ) -> dict:
        """List sessions with pagination."""
        offset = (page - 1) * page_size
        sessions = SessionDAO.get_all(status, page_size, offset)
        return {"sessions": sessions, "page": page, "page_size": page_size}

    @staticmethod
    def start_session(session_id: int, question_ids: list[int]) -> dict:
        """Start an interview session with selected questions."""
        session = SessionDAO.get_by_id(session_id)
        if not session:
            raise ValueError("Session not found")
        if session["status"] != "in_progress":
            raise ValueError("Session already started or completed")

        # Create interview questions from selected questions
        for idx, qid in enumerate(question_ids):
            question = QuestionDAO.get_by_id(qid)
            if question:
                InterviewQuestionDAO.create(
                    session_id=session_id,
                    question_text=question["title"],
                    question_id=qid,
                    order_index=idx,
                )

        return {"status": "started", "question_count": len(question_ids)}

    @staticmethod
    async def submit_answer(session_id: int, user_answer: str) -> dict:
        """Submit an answer and get feedback."""
        session = SessionDAO.get_by_id(session_id)
        if not session:
            raise ValueError("Session not found")
        if session["status"] != "in_progress":
            raise ValueError("Session is not active")

        # Get next unanswered question
        iq = InterviewQuestionDAO.get_next_unanswered(session_id)
        if not iq:
            raise ValueError("No more questions to answer")

        # Generate feedback
        try:
            feedback_data = await generate_interview_feedback(
                job_role=session["job_role"],
                question_text=iq["question_text"],
                user_answer=user_answer,
                question_index=iq["order_index"] + 1,
            )
        except Exception as e:
            logger.error(f"Feedback generation failed: {e}")
            feedback_data = {"feedback": "无法生成反馈，请稍后重试", "score": 0.0}

        # Save answer
        InterviewQuestionDAO.submit_answer(
            iq_id=iq["id"],
            user_answer=user_answer,
            ai_feedback=feedback_data["feedback"],
            score=feedback_data["score"],
        )

        # Check if follow-up is needed (score < 60 and not already a follow-up)
        followup_info = None
        score = feedback_data["score"]
        is_followup = bool(iq.get("is_followup", 0))

        if score < 60 and not is_followup:
            try:
                followup_text = await generate_followup_question(
                    job_role=session["job_role"],
                    question_text=iq["question_text"],
                    user_answer=user_answer,
                    feedback_summary=feedback_data["feedback"][
                        :500
                    ],  # Truncate
                    score=score,
                )
                if followup_text:
                    # Get next order_index
                    session_questions = InterviewQuestionDAO.get_by_session(
                        session_id
                    )
                    max_order = max(
                        [q["order_index"] for q in session_questions],
                        default=-1,
                    )

                    # Create follow-up question
                    followup_iq = InterviewQuestionDAO.create(
                        session_id=session_id,
                        question_text=followup_text,
                        order_index=max_order + 1,
                        is_followup=True,
                        parent_question_id=iq["id"],
                    )
                    followup_info = {
                        "id": followup_iq["id"],
                        "question_text": followup_text,
                        "order_index": followup_iq["order_index"],
                        "parent_question_id": iq["id"],
                    }
                    logger.info(
                        f"Created follow-up question for session "
                        f"{session_id}, parent {iq['id']}"
                    )
            except Exception as e:
                logger.error(f"Failed to generate follow-up: {e}")
                # Continue without follow-up on error

        # Check if there are more questions
        next_iq = InterviewQuestionDAO.get_next_unanswered(session_id)
        session_completed = next_iq is None

        if session_completed:
            SessionDAO.update_status(session_id, "completed")

        result = {
            "feedback": feedback_data["feedback"],
            "score": feedback_data["score"],
            "next_question": next_iq["question_text"] if next_iq else None,
            "session_completed": session_completed,
        }

        if followup_info:
            result["followup"] = followup_info

        return result

    @staticmethod
    async def submit_answer_stream(
        session_id: int, user_answer: str
    ) -> AsyncGenerator[dict, None]:
        """Submit an answer and stream feedback tokens.

        Yields dicts with keys:
            - type: 'token' | 'done' | 'error'
            - content: str
            - score: float (only in 'done')
            - next_question: str | None (only in 'done')
            - session_completed: bool (only in 'done')
        """
        session = SessionDAO.get_by_id(session_id)
        if not session:
            yield {"type": "error", "content": "会话未找到"}
            return
        if session["status"] != "in_progress":
            yield {"type": "error", "content": "会话不在进行中"}
            return

        iq = InterviewQuestionDAO.get_next_unanswered(session_id)
        if not iq:
            yield {"type": "error", "content": "没有更多题目"}
            return

        full_feedback = ""
        final_score = 0.0

        try:
            async for chunk in generate_interview_feedback_stream(
                job_role=session["job_role"],
                question_text=iq["question_text"],
                user_answer=user_answer,
                question_index=iq["order_index"] + 1,
            ):
                if chunk["type"] == "token":
                    full_feedback += chunk["content"]
                    yield chunk
                elif chunk["type"] == "done":
                    full_feedback = chunk["content"]
                    final_score = chunk["score"]
                    # Don't yield done yet - we need to add next_question info
                elif chunk["type"] == "error":
                    # If we have partial content, save it and continue
                    if full_feedback.strip():
                        logger.warning(f"Partial feedback received before error: {len(full_feedback)} chars")
                        final_score = 50.0  # Give a default score for partial feedback
                        # Don't yield error, proceed with partial content
                    else:
                        yield chunk
                        return
        except Exception as e:
            logger.error(f"Streaming feedback failed: {e}")
            # If we have accumulated content, treat as partial success
            if full_feedback.strip():
                logger.warning(f"Using partial feedback due to exception: {len(full_feedback)} chars")
                final_score = 50.0
            else:
                yield {"type": "error", "content": "反馈生成中断，请稍后重试"}
                return

        # Persist answer to DB
        try:
            InterviewQuestionDAO.submit_answer(
                iq_id=iq["id"],
                user_answer=user_answer,
                ai_feedback=full_feedback,
                score=final_score,
            )
        except Exception as e:
            logger.error(f"Failed to save answer: {e}")

        # Check if follow-up is needed (score < 60 and not already a follow-up)
        followup_info = None
        is_followup = bool(iq.get("is_followup", 0))

        if final_score < 60 and not is_followup:
            try:
                followup_text = await generate_followup_question(
                    job_role=session["job_role"],
                    question_text=iq["question_text"],
                    user_answer=user_answer,
                    feedback_summary=full_feedback[:500],  # Truncate
                    score=final_score,
                )
                if followup_text:
                    # Insert followup after current question using decimal order_index
                    parent_order = iq["order_index"]
                    next_order = parent_order + 0.5

                    # Create follow-up question
                    followup_iq = InterviewQuestionDAO.create(
                        session_id=session_id,
                        question_text=followup_text,
                        order_index=next_order,
                        is_followup=True,
                        parent_question_id=iq["id"],
                    )
                    followup_info = {
                        "id": followup_iq["id"],
                        "question_text": followup_text,
                        "order_index": followup_iq["order_index"],
                        "parent_question_id": iq["id"],
                    }
                    logger.info(
                        f"Created follow-up question for session "
                        f"{session_id}, parent {iq['id']}"
                    )
            except Exception as e:
                logger.error(f"Failed to generate follow-up in stream: {e}")
                # Continue without follow-up on error

        # Check completion
        next_iq = InterviewQuestionDAO.get_next_unanswered(session_id)
        session_completed = next_iq is None
        if session_completed:
            SessionDAO.update_status(session_id, "completed")

        done_event = {
            "type": "done",
            "content": full_feedback,
            "score": final_score,
            "next_question": next_iq["question_text"] if next_iq else None,
            "session_completed": session_completed,
        }

        if followup_info:
            done_event["followup"] = followup_info
            # Signal that followup choice should be shown
            done_event["show_followup_choice"] = True

        yield done_event

    @staticmethod
    def get_session_questions(session_id: int) -> list[dict]:
        """Get all questions in a session."""
        return InterviewQuestionDAO.get_by_session(session_id)

    @staticmethod
    def complete_session(session_id: int) -> dict:
        """Complete an interview session."""
        return SessionDAO.update_status(session_id, "completed")

    @staticmethod
    def get_session_stats(session_id: int) -> dict:
        """Get session statistics."""
        questions = InterviewQuestionDAO.get_by_session(session_id)
        answered = [q for q in questions if q["user_answer"]]
        scores = [q["score"] for q in answered if q["score"] is not None]

        return {
            "total_questions": len(questions),
            "answered": len(answered),
            "average_score": sum(scores) / len(scores) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
        }

    @staticmethod
    def pause_session(session_id: int) -> dict:
        """Pause an interview session."""
        session = SessionDAO.get_by_id(session_id)
        if not session:
            raise ValueError("Session not found")
        if session["status"] != "in_progress":
            raise ValueError("Only active sessions can be paused")

        result = SessionDAO.pause_session(session_id)
        logger.info(f"Session {session_id} paused")
        return result

    @staticmethod
    def resume_session(session_id: int) -> dict:
        """Resume a paused interview session."""
        session = SessionDAO.get_by_id(session_id)
        if not session:
            raise ValueError("Session not found")
        if session["status"] != "paused":
            raise ValueError("Only paused sessions can be resumed")

        result = SessionDAO.resume_session(session_id)
        logger.info(f"Session {session_id} resumed")
        return result

    @staticmethod
    def skip_question(session_id: int) -> dict:
        """Skip the current unanswered question."""
        session = SessionDAO.get_by_id(session_id)
        if not session:
            raise ValueError("Session not found")
        if session["status"] != "in_progress":
            raise ValueError("Session is not active")

        iq = InterviewQuestionDAO.get_next_unanswered(session_id)
        if not iq:
            raise ValueError("No more questions to skip")

        InterviewQuestionDAO.skip_question(iq["id"])
        logger.info(f"Question {iq['id']} in session {session_id} skipped")

        # Check if there are more questions
        next_iq = InterviewQuestionDAO.get_next_unanswered(session_id)
        session_completed = next_iq is None

        if session_completed:
            SessionDAO.update_status(session_id, "completed")

        return {
            "skipped_question_id": iq["id"],
            "next_question": next_iq["question_text"] if next_iq else None,
            "session_completed": session_completed,
        }

    @staticmethod
    def save_draft(session_id: int, question_id: int, draft_text: str) -> dict:
        """Save answer draft for a question."""
        session = SessionDAO.get_by_id(session_id)
        if not session:
            raise ValueError("Session not found")

        iq = InterviewQuestionDAO.get_by_id(question_id)
        if not iq:
            raise ValueError("Question not found")
        if iq["session_id"] != session_id:
            raise ValueError("Question does not belong to this session")

        result = InterviewQuestionDAO.save_draft(question_id, draft_text)
        logger.info(f"Draft saved for question {question_id} in session {session_id}")
        return result

    @staticmethod
    def bookmark_question(question_id: int, bookmarked: bool) -> dict:
        """Toggle bookmark status for a question."""
        iq = InterviewQuestionDAO.get_by_id(question_id)
        if not iq:
            raise ValueError("Question not found")

        result = InterviewQuestionDAO.update_bookmark(question_id, bookmarked)
        action = "bookmarked" if bookmarked else "unbookmarked"
        logger.info(f"Question {question_id} {action}")
        return result

    @staticmethod
    def add_question_note(question_id: int, note: str) -> dict:
        """Add or update note for a question."""
        iq = InterviewQuestionDAO.get_by_id(question_id)
        if not iq:
            raise ValueError("Question not found")

        result = InterviewQuestionDAO.update_note(question_id, note)
        logger.info(f"Note updated for question {question_id}")
        return result

    @staticmethod
    def update_question_time(question_id: int, time_spent: int) -> dict:
        """Update time spent on a question."""
        iq = InterviewQuestionDAO.get_by_id(question_id)
        if not iq:
            raise ValueError("Question not found")

        result = InterviewQuestionDAO.update_time_spent(question_id, time_spent)
        logger.debug(f"Time spent updated for question {question_id}: {time_spent}s")
        return result

    @staticmethod
    async def edit_answer_stream(
        session_id: int, question_id: int, user_answer: str
    ) -> AsyncGenerator[dict, None]:
        """Edit an existing answer and stream new feedback.

        Args:
            session_id: The session ID.
            question_id: The question ID to edit.
            user_answer: The new answer text.

        Yields:
            Stream events similar to submit_answer_stream.
        """
        session = SessionDAO.get_by_id(session_id)
        if not session:
            yield {"type": "error", "content": "会话未找到"}
            return

        iq = InterviewQuestionDAO.get_by_id(question_id)
        if not iq:
            yield {"type": "error", "content": "题目未找到"}
            return
        if iq["session_id"] != session_id:
            yield {"type": "error", "content": "题目不属于此会话"}
            return

        # Update answer and increment edit_count
        try:
            InterviewQuestionDAO.update_answer(question_id, user_answer)
        except Exception as e:
            logger.error(f"Failed to update answer: {e}")
            yield {"type": "error", "content": "更新答案失败"}
            return

        full_feedback = ""
        final_score = 0.0

        # Generate new feedback (streaming)
        try:
            async for chunk in generate_interview_feedback_stream(
                job_role=session["job_role"],
                question_text=iq["question_text"],
                user_answer=user_answer,
                question_index=iq["order_index"] + 1,
            ):
                if chunk["type"] == "token":
                    full_feedback += chunk["content"]
                    yield chunk
                elif chunk["type"] == "done":
                    full_feedback = chunk["content"]
                    final_score = chunk["score"]
                elif chunk["type"] == "error":
                    if full_feedback.strip():
                        logger.warning(f"Partial feedback during edit: {len(full_feedback)} chars")
                        final_score = 50.0
                    else:
                        yield chunk
                        return
        except Exception as e:
            logger.error(f"Streaming feedback failed during edit: {e}")
            if full_feedback.strip():
                logger.warning(f"Using partial feedback: {len(full_feedback)} chars")
                final_score = 50.0
            else:
                yield {"type": "error", "content": "反馈生成中断"}
                return

        # Update feedback and score
        try:
            InterviewQuestionDAO.submit_answer(
                iq_id=question_id,
                user_answer=user_answer,
                ai_feedback=full_feedback,
                score=final_score,
            )
        except Exception as e:
            logger.error(f"Failed to save edited feedback: {e}")

        # Check if new score triggers followup (< 60 and not already a followup)
        followup_info = None
        is_followup = bool(iq.get("is_followup", 0))

        if final_score < 60 and not is_followup:
            try:
                followup_text = await generate_followup_question(
                    job_role=session["job_role"],
                    question_text=iq["question_text"],
                    user_answer=user_answer,
                    feedback_summary=full_feedback[:500],
                    score=final_score,
                )
                if followup_text:
                    # Insert followup after the edited question
                    parent_order = iq["order_index"]
                    next_order = parent_order + 0.5

                    followup_iq = InterviewQuestionDAO.create(
                        session_id=session_id,
                        question_text=followup_text,
                        order_index=next_order,
                        is_followup=True,
                        parent_question_id=iq["id"],
                    )
                    followup_info = {
                        "question_text": followup_text,
                        "order_index": followup_iq["order_index"],
                        "parent_question_id": iq["id"],
                    }
                    logger.info(
                        f"Created follow-up after edit for question {question_id}"
                    )
            except Exception as e:
                logger.error(f"Failed to generate follow-up after edit: {e}")

        done_event = {
            "type": "done",
            "content": full_feedback,
            "score": final_score,
            "is_edit": True,
        }

        if followup_info:
            done_event["followup"] = followup_info

        yield done_event

    @staticmethod
    def skip_followup_question(session_id: int, question_id: int) -> dict:
        """Skip a followup question.

        Args:
            session_id: The session ID.
            question_id: The followup question ID to skip.

        Returns:
            Dict with next_question and session_completed status.
        """
        session = SessionDAO.get_by_id(session_id)
        if not session:
            raise ValueError("会话未找到")

        iq = InterviewQuestionDAO.get_by_id(question_id)
        if not iq:
            raise ValueError("题目未找到")
        if iq["session_id"] != session_id:
            raise ValueError("题目不属于此会话")

        # Mark as skipped
        InterviewQuestionDAO.update_status(question_id, "skipped")
        logger.info(f"Followup question {question_id} skipped in session {session_id}")

        # Get next unanswered question
        next_iq = InterviewQuestionDAO.get_next_unanswered(session_id)
        session_completed = next_iq is None

        if session_completed:
            SessionDAO.update_status(session_id, "completed")

        return {
            "skipped_question_id": question_id,
            "next_question": next_iq["question_text"] if next_iq else None,
            "session_completed": session_completed,
        }

    @staticmethod
    def update_session_metadata(session_id: int, tags: Optional[str] = None, notes: Optional[str] = None) -> dict:
        """Update session tags and notes."""
        session = SessionDAO.get_by_id(session_id)
        if not session:
            raise ValueError("Session not found")

        result = SessionDAO.update_metadata(session_id, tags, notes)
        logger.info(f"Metadata updated for session {session_id}")
        return result

    @staticmethod
    def restart_session(session_id: int) -> dict:
        """Restart a completed session by creating a new clone.

        Args:
            session_id: ID of the completed session to restart.

        Returns:
            The newly created session dict.

        Raises:
            ValueError: If session not found or not completed.
        """
        session = SessionDAO.get_by_id(session_id)
        if not session:
            raise ValueError("会话未找到")

        if session["status"] != "completed":
            raise ValueError("只能重新开始已完成的面试")

        # Generate new title
        retry_count = session.get("retry_count", 0) + 1
        new_title = f"{session['title']} - 重做 {retry_count}"

        # Clone session
        new_session = SessionDAO.clone_session(session_id, new_title)
        logger.info(f"Restarted session {session_id} as new session {new_session['id']}")
        return new_session

    @staticmethod
    def batch_delete_sessions(session_ids: list[int]) -> int:
        """Batch delete sessions.

        Args:
            session_ids: List of session IDs to delete.

        Returns:
            Count of deleted sessions.

        Raises:
            ValueError: If no sessions selected.
        """
        if not session_ids:
            raise ValueError("未选择会话")

        deleted = SessionDAO.delete_multiple(session_ids)
        logger.info(f"Batch deleted {deleted} sessions")
        return deleted

    @staticmethod
    def batch_export_sessions(session_ids: list[int], format: str = "json") -> dict:
        """Batch export sessions data.

        Args:
            session_ids: List of session IDs to export.
            format: Export format ('json' or 'csv').

        Returns:
            Dict with 'format' and 'data' keys.

        Raises:
            ValueError: If no sessions selected.
        """
        if not session_ids:
            raise ValueError("未选择会话")

        sessions = SessionDAO.get_multiple_with_details(session_ids)

        if format == "csv":
            # Generate CSV data (flat structure)
            csv_data = _generate_csv(sessions)
            return {"format": "csv", "data": csv_data}
        else:
            # Return JSON data
            return {"format": "json", "data": sessions}

    @staticmethod
    def batch_update_tags(session_ids: list[int], tags_to_add: list[str], tags_to_remove: list[str]) -> int:
        """Batch update session tags.

        Args:
            session_ids: List of session IDs to update.
            tags_to_add: List of tags to add.
            tags_to_remove: List of tags to remove.

        Returns:
            Count of updated sessions.

        Raises:
            ValueError: If no sessions selected.
        """
        if not session_ids:
            raise ValueError("未选择会话")

        updated = 0
        for sid in session_ids:
            session = SessionDAO.get_by_id(sid)
            if not session:
                continue

            # Parse existing tags
            current_tags = set(session.get("tags", "").split(",") if session.get("tags") else [])
            current_tags = {t.strip() for t in current_tags if t.strip()}

            # Add new tags
            current_tags.update(t.strip() for t in tags_to_add if t.strip())

            # Remove tags
            current_tags.difference_update(t.strip() for t in tags_to_remove if t.strip())

            # Update
            new_tags = ",".join(sorted(current_tags))
            SessionDAO.update_metadata(sid, tags=new_tags)
            updated += 1

        logger.info(f"Batch updated tags for {updated} sessions")
        return updated


def _generate_csv(sessions: list[dict]) -> str:
    """Generate CSV string from sessions data.

    Args:
        sessions: List of session dicts with questions included.

    Returns:
        CSV string with headers and rows.
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        "会话ID", "会话标题", "职位", "状态", "创建时间", "完成时间",
        "题目ID", "题目文本", "用户回答", "AI反馈", "得分", "回答时间"
    ])

    # Write rows
    for session in sessions:
        session_id = session["id"]
        session_title = session["title"]
        job_role = session.get("job_role", "")
        status = session["status"]
        created_at = session["created_at"]
        completed_at = session.get("completed_at", "")

        questions = session.get("questions", [])
        if not questions:
            # Session with no questions
            writer.writerow([
                session_id, session_title, job_role, status, created_at, completed_at,
                "", "", "", "", "", ""
            ])
        else:
            for q in questions:
                writer.writerow([
                    session_id, session_title, job_role, status, created_at, completed_at,
                    q.get("id", ""), q.get("question_text", ""), q.get("user_answer", ""),
                    q.get("ai_feedback", ""), q.get("score", ""), q.get("answered_at", "")
                ])

    return output.getvalue()
