"""Tests for interview engine: session lifecycle, follow-up generation, and stats.

Covers:
- create_session, start_session, submit_answer, complete_session
- Follow-up question generation when score < 60
- Follow-ups do NOT trigger secondary follow-ups
- Session statistics calculation
- Streaming submit_answer_stream
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.database import init_db, close_db
from app.models.db_models import SessionDAO, InterviewQuestionDAO, QuestionDAO
from app.services.interview_engine import InterviewEngine


@pytest.fixture(autouse=True)
def setup_db():
    """Initialize a fresh database for each test."""
    init_db()
    yield
    close_db()


def _create_question(title: str = "What is Python?") -> dict:
    """Helper to create a question in the DB."""
    return QuestionDAO.create(
        title=title,
        category="技术",
        difficulty="medium",
        tags="python",
        expected_answer="A programming language.",
    )


def _create_session_with_questions(count: int = 2) -> tuple[dict, list[dict]]:
    """Create a session and attach N questions to it."""
    session = SessionDAO.create("Test Interview", "Python Developer")
    questions = []
    for i in range(count):
        q = _create_question(f"Question {i+1}")
        questions.append(q)
        InterviewQuestionDAO.create(
            session_id=session["id"],
            question_text=q["title"],
            question_id=q["id"],
            order_index=i,
        )
    return session, questions


class TestSessionLifecycle:
    """Tests for basic session CRUD operations."""

    def test_create_session(self):
        """Creating a session returns valid dict with correct status."""
        session = InterviewEngine.create_session("My Interview", "Backend Dev")
        assert session["title"] == "My Interview"
        assert session["job_role"] == "Backend Dev"
        assert session["status"] == "in_progress"

    def test_get_session(self):
        """Getting a session by ID returns the correct record."""
        session = InterviewEngine.create_session("Lookup Test")
        fetched = InterviewEngine.get_session(session["id"])
        assert fetched is not None
        assert fetched["title"] == "Lookup Test"

    def test_get_session_not_found(self):
        """Getting a non-existent session returns None."""
        result = InterviewEngine.get_session(99999)
        assert result is None

    def test_list_sessions(self):
        """Listing sessions returns paginated results."""
        InterviewEngine.create_session("Session A")
        InterviewEngine.create_session("Session B")
        result = InterviewEngine.list_sessions(page=1, page_size=10)
        assert "sessions" in result
        assert len(result["sessions"]) >= 2

    def test_start_session(self):
        """Starting a session creates interview questions from selected IDs."""
        session = SessionDAO.create("Start Test")
        q1 = _create_question("Q1")
        q2 = _create_question("Q2")

        result = InterviewEngine.start_session(session["id"], [q1["id"], q2["id"]])
        assert result["status"] == "started"
        assert result["question_count"] == 2

        # Verify interview questions were created
        iq_list = InterviewQuestionDAO.get_by_session(session["id"])
        assert len(iq_list) == 2

    def test_start_session_not_found(self):
        """Starting a non-existent session raises ValueError."""
        with pytest.raises(ValueError, match="Session not found"):
            InterviewEngine.start_session(99999, [1])

    def test_start_session_already_completed(self):
        """Starting an already completed session raises ValueError."""
        session = SessionDAO.create("Completed Session")
        SessionDAO.update_status(session["id"], "completed")

        with pytest.raises(ValueError, match="already started or completed"):
            InterviewEngine.start_session(session["id"], [])

    def test_complete_session(self):
        """Completing a session updates its status."""
        session = InterviewEngine.create_session("To Complete")
        result = InterviewEngine.complete_session(session["id"])
        assert result["status"] == "completed"

    def test_get_session_questions(self):
        """Getting session questions returns all attached questions."""
        session, questions = _create_session_with_questions(3)
        iq_list = InterviewEngine.get_session_questions(session["id"])
        assert len(iq_list) == 3


class TestSubmitAnswer:
    """Tests for answer submission and feedback generation."""

    @pytest.mark.asyncio
    async def test_submit_answer_success(self):
        """Submitting an answer generates feedback and saves it."""
        session, _ = _create_session_with_questions(1)

        mock_feedback = {"feedback": "Good answer!", "score": 85.0}
        with patch(
            "app.services.interview_engine.generate_interview_feedback",
            new_callable=AsyncMock,
            return_value=mock_feedback,
        ):
            result = await InterviewEngine.submit_answer(
                session["id"], "Python is great"
            )

        assert result["feedback"] == "Good answer!"
        assert result["score"] == 85.0
        assert "followup" not in result  # Score >= 60, no follow-up

    @pytest.mark.asyncio
    async def test_submit_answer_no_more_questions(self):
        """Submitting when no unanswered questions remain raises ValueError.

        Note: When the last question is answered, the session auto-completes.
        A subsequent submit will fail with 'not active' (session completed)
        rather than 'No more questions'. We test both paths:
        - If session stays active: 'No more questions'
        - If session auto-completed: 'not active'
        """
        session, _ = _create_session_with_questions(1)

        # Answer the only question first
        with patch(
            "app.services.interview_engine.generate_interview_feedback",
            new_callable=AsyncMock,
            return_value={"feedback": "OK", "score": 90.0},
        ):
            await InterviewEngine.submit_answer(session["id"], "answer")

        # Now try again — should fail (session auto-completed or no questions)
        with pytest.raises(ValueError):
            await InterviewEngine.submit_answer(session["id"], "another answer")

    @pytest.mark.asyncio
    async def test_submit_answer_session_not_active(self):
        """Submitting to a completed session raises ValueError."""
        session, _ = _create_session_with_questions(1)
        SessionDAO.update_status(session["id"], "completed")

        with pytest.raises(ValueError, match="not active"):
            await InterviewEngine.submit_answer(session["id"], "answer")

    @pytest.mark.asyncio
    async def test_submit_answer_llm_failure_graceful_fallback(self):
        """LLM failure during feedback falls back to default response."""
        session, _ = _create_session_with_questions(1)

        with patch(
            "app.services.interview_engine.generate_interview_feedback",
            new_callable=AsyncMock,
            side_effect=Exception("LLM down"),
        ):
            result = await InterviewEngine.submit_answer(session["id"], "answer")

        assert result["feedback"] == "无法生成反馈，请稍后重试"
        assert result["score"] == 0.0

    @pytest.mark.asyncio
    async def test_submit_answer_completes_session_when_done(self):
        """Session auto-completes when all questions are answered."""
        session, _ = _create_session_with_questions(1)

        with patch(
            "app.services.interview_engine.generate_interview_feedback",
            new_callable=AsyncMock,
            return_value={"feedback": "Done", "score": 90.0},
        ):
            result = await InterviewEngine.submit_answer(session["id"], "final answer")

        assert result["session_completed"] is True
        updated = SessionDAO.get_by_id(session["id"])
        assert updated["status"] == "completed"


class TestFollowUpGeneration:
    """Tests for follow-up question logic."""

    @pytest.mark.asyncio
    async def test_followup_generated_on_low_score(self):
        """A follow-up question is created when score < 60."""
        session, _ = _create_session_with_questions(1)

        with (
            patch(
                "app.services.interview_engine.generate_interview_feedback",
                new_callable=AsyncMock,
                return_value={"feedback": "Needs improvement", "score": 40.0},
            ),
            patch(
                "app.services.interview_engine.generate_followup_question",
                new_callable=AsyncMock,
                return_value="Can you elaborate on that?",
            ),
        ):
            result = await InterviewEngine.submit_answer(session["id"], "weak answer")

        assert "followup" in result
        assert result["followup"]["question_text"] == "Can you elaborate on that?"
        assert result["session_completed"] is False  # Follow-up is now pending

        # Verify follow-up was persisted
        iq_list = InterviewQuestionDAO.get_by_session(session["id"])
        assert len(iq_list) == 2
        followup_iq = iq_list[-1]
        assert followup_iq["is_followup"] == 1
        assert followup_iq["question_text"] == "Can you elaborate on that?"

    @pytest.mark.asyncio
    async def test_no_followup_on_high_score(self):
        """No follow-up is generated when score >= 60."""
        session, _ = _create_session_with_questions(1)

        with patch(
            "app.services.interview_engine.generate_interview_feedback",
            new_callable=AsyncMock,
            return_value={"feedback": "Great!", "score": 75.0},
        ):
            result = await InterviewEngine.submit_answer(session["id"], "good answer")

        assert "followup" not in result

    @pytest.mark.asyncio
    async def test_no_secondary_followup(self):
        """Answering a follow-up with low score does NOT generate another follow-up."""
        session, _ = _create_session_with_questions(1)

        # First: answer original question with low score → triggers follow-up
        with (
            patch(
                "app.services.interview_engine.generate_interview_feedback",
                new_callable=AsyncMock,
                return_value={"feedback": "Weak", "score": 30.0},
            ),
            patch(
                "app.services.interview_engine.generate_followup_question",
                new_callable=AsyncMock,
                return_value="Follow-up Q",
            ),
        ):
            await InterviewEngine.submit_answer(session["id"], "bad answer")

        # Second: answer the follow-up with low score → should NOT trigger another
        with (
            patch(
                "app.services.interview_engine.generate_interview_feedback",
                new_callable=AsyncMock,
                return_value={"feedback": "Still weak", "score": 20.0},
            ),
            patch(
                "app.services.interview_engine.generate_followup_question",
                new_callable=AsyncMock,
            ) as mock_followup,
        ):
            result = await InterviewEngine.submit_answer(session["id"], "still bad")

        # Follow-up generator should NOT have been called for the follow-up question
        mock_followup.assert_not_called()
        assert "followup" not in result

    @pytest.mark.asyncio
    async def test_followup_generation_failure_continues(self):
        """If follow-up generation fails, the answer submission still succeeds."""
        session, _ = _create_session_with_questions(1)

        with (
            patch(
                "app.services.interview_engine.generate_interview_feedback",
                new_callable=AsyncMock,
                return_value={"feedback": "Poor", "score": 25.0},
            ),
            patch(
                "app.services.interview_engine.generate_followup_question",
                new_callable=AsyncMock,
                side_effect=Exception("Follow-up LLM error"),
            ),
        ):
            result = await InterviewEngine.submit_answer(session["id"], "bad")

        # Should succeed without followup key
        assert result["score"] == 25.0
        assert "followup" not in result

    @pytest.mark.asyncio
    async def test_followup_returns_none_continues(self):
        """If follow-up generator returns None, no follow-up is created."""
        session, _ = _create_session_with_questions(1)

        with (
            patch(
                "app.services.interview_engine.generate_interview_feedback",
                new_callable=AsyncMock,
                return_value={"feedback": "Poor", "score": 30.0},
            ),
            patch(
                "app.services.interview_engine.generate_followup_question",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await InterviewEngine.submit_answer(session["id"], "bad")

        assert "followup" not in result


class TestSessionStats:
    """Tests for session statistics calculation."""

    def test_stats_empty_session(self):
        """Stats for a session with no questions returns zeros."""
        session = SessionDAO.create("Empty Stats")
        stats = InterviewEngine.get_session_stats(session["id"])
        assert stats["total_questions"] == 0
        assert stats["answered"] == 0
        assert stats["average_score"] == 0

    def test_stats_with_answers(self):
        """Stats correctly compute average, min, max scores."""
        session, _ = _create_session_with_questions(3)
        iq_list = InterviewQuestionDAO.get_by_session(session["id"])

        # Submit answers with known scores
        InterviewQuestionDAO.submit_answer(iq_list[0]["id"], "a1", "fb1", 80.0)
        InterviewQuestionDAO.submit_answer(iq_list[1]["id"], "a2", "fb2", 60.0)
        # Third question left unanswered

        stats = InterviewEngine.get_session_stats(session["id"])
        assert stats["total_questions"] == 3
        assert stats["answered"] == 2
        assert stats["average_score"] == 70.0
        assert stats["min_score"] == 60.0
        assert stats["max_score"] == 80.0

    def test_stats_all_answered(self):
        """Stats when all questions are answered."""
        session, _ = _create_session_with_questions(2)
        iq_list = InterviewQuestionDAO.get_by_session(session["id"])

        InterviewQuestionDAO.submit_answer(iq_list[0]["id"], "a1", "fb1", 90.0)
        InterviewQuestionDAO.submit_answer(iq_list[1]["id"], "a2", "fb2", 90.0)

        stats = InterviewEngine.get_session_stats(session["id"])
        assert stats["answered"] == 2
        assert stats["average_score"] == 90.0


class TestSubmitAnswerStream:
    """Tests for streaming answer submission."""

    @pytest.mark.asyncio
    async def test_stream_success(self):
        """Streaming yields token events followed by a done event."""
        session, _ = _create_session_with_questions(1)

        async def mock_stream(**kwargs):
            yield {"type": "token", "content": "Good "}
            yield {"type": "token", "content": "answer!"}
            yield {"type": "done", "content": "Good answer!", "score": 85.0}

        with patch(
            "app.services.interview_engine.generate_interview_feedback_stream",
            side_effect=lambda **kw: mock_stream(**kw),
        ):
            events = []
            async for event in InterviewEngine.submit_answer_stream(
                session["id"], "my answer"
            ):
                events.append(event)

        # Should have token events + final done event
        token_events = [e for e in events if e["type"] == "token"]
        done_events = [e for e in events if e["type"] == "done"]
        assert len(token_events) == 2
        assert len(done_events) == 1
        assert done_events[0]["score"] == 85.0

    @pytest.mark.asyncio
    async def test_stream_session_not_found(self):
        """Streaming yields error event for non-existent session."""
        events = []
        async for event in InterviewEngine.submit_answer_stream(99999, "answer"):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"

    @pytest.mark.asyncio
    async def test_stream_no_more_questions(self):
        """Streaming yields error when no unanswered questions remain."""
        session, _ = _create_session_with_questions(1)

        # Answer the only question
        iq = InterviewQuestionDAO.get_next_unanswered(session["id"])
        InterviewQuestionDAO.submit_answer(iq["id"], "done", "fb", 90.0)

        events = []
        async for event in InterviewEngine.submit_answer_stream(
            session["id"], "answer"
        ):
            events.append(event)

        assert events[0]["type"] == "error"
        assert "没有更多题目" in events[0]["content"]
