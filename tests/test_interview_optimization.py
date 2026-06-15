"""Tests for interview optimization features."""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.db_models import SessionDAO, InterviewQuestionDAO, QuestionDAO

client = TestClient(app)


class TestSessionManagement:
    """Test session pause/resume and metadata updates."""

    def test_pause_session(self):
        """Test pausing an active session."""
        # Create session
        response = client.post("/api/sessions", json={"title": "Test Pause", "job_role": "Engineer"})
        assert response.status_code == 200
        session_id = response.json()["id"]

        # Pause session
        response = client.post(f"/api/sessions/{session_id}/pause")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "paused"
        assert data["paused_at"] is not None

        # Cleanup
        SessionDAO.delete(session_id)

    def test_resume_session(self):
        """Test resuming a paused session."""
        # Create and pause session
        session = SessionDAO.create("Test Resume", "Engineer")
        session_id = session["id"]
        SessionDAO.pause_session(session_id)

        # Resume session
        response = client.post(f"/api/sessions/{session_id}/resume")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"
        assert data["paused_at"] is None

        # Cleanup
        SessionDAO.delete(session_id)

    def test_update_session_metadata(self):
        """Test updating session tags and notes."""
        # Create session
        session = SessionDAO.create("Test Metadata", "Engineer")
        session_id = session["id"]

        # Update metadata
        response = client.patch(
            f"/api/sessions/{session_id}",
            json={"tags": "important,review", "notes": "Test notes"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tags"] == "important,review"
        assert data["notes"] == "Test notes"

        # Cleanup
        SessionDAO.delete(session_id)


class TestQuestionOperations:
    """Test question draft, bookmark, note, and time tracking."""

    def test_save_draft(self):
        """Test saving answer draft."""
        # Create session and question
        session = SessionDAO.create("Test Draft", "Engineer")
        question = QuestionDAO.create("Test Q", "技术", "medium", "", "")
        iq = InterviewQuestionDAO.create(session["id"], "Test Q", question["id"], 0)

        # Save draft
        response = client.post(
            f"/api/sessions/{session['id']}/questions/{iq['id']}/draft",
            json={"draft_text": "This is my draft answer"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["draft_answer"] == "This is my draft answer"

        # Cleanup
        SessionDAO.delete(session["id"])
        QuestionDAO.delete(question["id"])

    def test_bookmark_question(self):
        """Test bookmarking a question."""
        # Create session and question
        session = SessionDAO.create("Test Bookmark", "Engineer")
        question = QuestionDAO.create("Test Q", "技术", "medium", "", "")
        iq = InterviewQuestionDAO.create(session["id"], "Test Q", question["id"], 0)

        # Bookmark
        response = client.put(
            f"/api/sessions/{session['id']}/questions/{iq['id']}/bookmark",
            json={"bookmarked": True}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_bookmarked"] == 1

        # Unbookmark
        response = client.put(
            f"/api/sessions/{session['id']}/questions/{iq['id']}/bookmark",
            json={"bookmarked": False}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_bookmarked"] == 0

        # Cleanup
        SessionDAO.delete(session["id"])
        QuestionDAO.delete(question["id"])

    def test_add_question_note(self):
        """Test adding notes to a question."""
        # Create session and question
        session = SessionDAO.create("Test Note", "Engineer")
        question = QuestionDAO.create("Test Q", "技术", "medium", "", "")
        iq = InterviewQuestionDAO.create(session["id"], "Test Q", question["id"], 0)

        # Add note
        response = client.put(
            f"/api/sessions/{session['id']}/questions/{iq['id']}/note",
            json={"note": "Important: Review this question"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["notes"] == "Important: Review this question"

        # Cleanup
        SessionDAO.delete(session["id"])
        QuestionDAO.delete(question["id"])

    def test_update_question_time(self):
        """Test updating time spent on a question."""
        # Create session and question
        session = SessionDAO.create("Test Time", "Engineer")
        question = QuestionDAO.create("Test Q", "技术", "medium", "", "")
        iq = InterviewQuestionDAO.create(session["id"], "Test Q", question["id"], 0)

        # Update time
        response = client.put(
            f"/api/sessions/{session['id']}/questions/{iq['id']}/time",
            json={"time_spent": 180}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["time_spent"] == 180

        # Cleanup
        SessionDAO.delete(session["id"])
        QuestionDAO.delete(question["id"])

    def test_skip_question(self):
        """Test skipping a question."""
        # Create session with question
        session = SessionDAO.create("Test Skip", "Engineer")
        question = QuestionDAO.create("Test Q", "技术", "medium", "", "")
        iq = InterviewQuestionDAO.create(session["id"], "Test Q", question["id"], 0)

        # Skip question
        response = client.post(f"/api/sessions/{session['id']}/skip")
        assert response.status_code == 200
        data = response.json()
        assert data["skipped_question_id"] == iq["id"]
        assert data["session_completed"] is True  # No more questions

        # Verify question marked as skipped
        skipped_iq = InterviewQuestionDAO.get_by_id(iq["id"])
        assert skipped_iq["user_answer"] == "[SKIPPED]"
        assert skipped_iq["score"] == -1

        # Cleanup
        SessionDAO.delete(session["id"])
        QuestionDAO.delete(question["id"])


class TestStatistics:
    """Test statistics API endpoints."""

    def test_get_session_statistics(self):
        """Test getting detailed session statistics."""
        # Create session with answered questions
        session = SessionDAO.create("Stats Test", "Engineer")
        for i in range(3):
            q = QuestionDAO.create(f"Q{i+1}", "技术", "medium", "", "")
            iq = InterviewQuestionDAO.create(session["id"], f"Q{i+1}", q["id"], i)
            InterviewQuestionDAO.submit_answer(iq["id"], f"A{i+1}", f"F{i+1}", 70 + i * 10)
            InterviewQuestionDAO.update_time_spent(iq["id"], 60 + i * 30)

        # Get statistics
        response = client.get(f"/api/sessions/{session['id']}/statistics")
        assert response.status_code == 200
        data = response.json()

        assert data["counts"]["total"] == 3
        assert data["counts"]["answered"] == 3
        assert data["scores"]["average"] == 80.0
        assert data["progress"]["percentage"] == 100.0

        # Cleanup
        SessionDAO.delete(session["id"])

    def test_get_time_analysis(self):
        """Test getting time analysis."""
        # Create session with answered questions
        session = SessionDAO.create("Time Test", "Engineer")
        for i in range(2):
            q = QuestionDAO.create(f"Q{i+1}", "技术", "medium", "", "")
            iq = InterviewQuestionDAO.create(session["id"], f"Q{i+1}", q["id"], i)
            InterviewQuestionDAO.submit_answer(iq["id"], f"A{i+1}", f"F{i+1}", 80)
            InterviewQuestionDAO.update_time_spent(iq["id"], 60 + i * 60)

        # Get time analysis
        response = client.get(f"/api/sessions/{session['id']}/statistics/time")
        assert response.status_code == 200
        data = response.json()

        assert len(data["questions"]) == 2
        assert data["quartiles"]["median"] in [60, 120]

        # Cleanup
        SessionDAO.delete(session["id"])

    def test_get_score_distribution(self):
        """Test getting score distribution."""
        # Create session with varied scores
        session = SessionDAO.create("Score Test", "Engineer")
        scores = [30, 50, 70, 90]
        for i, score in enumerate(scores):
            q = QuestionDAO.create(f"Q{i+1}", "技术", "medium", "", "")
            iq = InterviewQuestionDAO.create(session["id"], f"Q{i+1}", q["id"], i)
            InterviewQuestionDAO.submit_answer(iq["id"], f"A{i+1}", f"F{i+1}", score)

        # Get distribution
        response = client.get(f"/api/sessions/{session['id']}/statistics/scores")
        assert response.status_code == 200
        data = response.json()

        assert data["total_scored"] == 4
        assert data["distribution"]["poor"] == 1  # score < 40
        assert data["distribution"]["fair"] == 1  # 40 <= score < 60
        assert data["distribution"]["good"] == 1  # 60 <= score < 80
        assert data["distribution"]["excellent"] == 1  # score >= 80

        # Cleanup
        SessionDAO.delete(session["id"])

    def test_get_category_performance(self):
        """Test getting category performance."""
        # Create session with regular and followup questions
        session = SessionDAO.create("Category Test", "Engineer")

        # Regular question
        q1 = QuestionDAO.create("Q1", "技术", "medium", "", "")
        iq1 = InterviewQuestionDAO.create(session["id"], "Q1", q1["id"], 0, False, None)
        InterviewQuestionDAO.submit_answer(iq1["id"], "A1", "F1", 80)

        # Followup question
        iq2 = InterviewQuestionDAO.create(session["id"], "Q2", None, 1, True, iq1["id"])
        InterviewQuestionDAO.submit_answer(iq2["id"], "A2", "F2", 60)

        # Get performance
        response = client.get(f"/api/sessions/{session['id']}/statistics/category")
        assert response.status_code == 200
        data = response.json()

        assert data["regular"]["count"] == 1
        assert data["followup"]["count"] == 1
        assert data["regular"]["avg_score"] == 80.0
        assert data["followup"]["avg_score"] == 60.0

        # Cleanup
        SessionDAO.delete(session["id"])


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_pause_nonexistent_session(self):
        """Test pausing a non-existent session."""
        response = client.post("/api/sessions/99999/pause")
        assert response.status_code == 400

    def test_resume_active_session(self):
        """Test resuming an already active session."""
        session = SessionDAO.create("Active", "Engineer")
        response = client.post(f"/api/sessions/{session['id']}/resume")
        assert response.status_code == 400
        SessionDAO.delete(session["id"])

    def test_skip_no_questions(self):
        """Test skipping when no questions exist."""
        session = SessionDAO.create("Empty", "Engineer")
        response = client.post(f"/api/sessions/{session['id']}/skip")
        assert response.status_code == 400
        SessionDAO.delete(session["id"])

    def test_save_draft_wrong_session(self):
        """Test saving draft for question in different session."""
        session1 = SessionDAO.create("Session 1", "Engineer")
        session2 = SessionDAO.create("Session 2", "Engineer")
        q = QuestionDAO.create("Q", "技术", "medium", "", "")
        iq = InterviewQuestionDAO.create(session1["id"], "Q", q["id"], 0)

        response = client.post(
            f"/api/sessions/{session2['id']}/questions/{iq['id']}/draft",
            json={"draft_text": "Draft"}
        )
        assert response.status_code == 400

        SessionDAO.delete(session1["id"])
        SessionDAO.delete(session2["id"])
        QuestionDAO.delete(q["id"])
