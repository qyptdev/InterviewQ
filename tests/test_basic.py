"""Basic tests for InterviewQ application."""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db


@pytest.fixture
def client():
    """Create test client."""
    init_db()
    with TestClient(app) as c:
        yield c


def test_health_check(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"


def test_index_page(client):
    """Test index page loads."""
    response = client.get("/")
    assert response.status_code == 200
    assert "InterviewQ" in response.text


def test_questions_page(client):
    """Test questions page loads."""
    response = client.get("/questions")
    assert response.status_code == 200


def test_sessions_page(client):
    """Test sessions page loads."""
    response = client.get("/sessions")
    assert response.status_code == 200


def test_banks_page(client):
    """Test banks page loads."""
    response = client.get("/banks")
    assert response.status_code == 200


def test_create_question(client):
    """Test creating a question via API."""
    response = client.post(
        "/api/questions",
        json={
            "title": "What is Python?",
            "category": "技术",
            "difficulty": "easy",
            "tags": "Python,basics",
            "expected_answer": "Python is a programming language.",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "What is Python?"
    assert data["category"] == "技术"


def test_list_questions(client):
    """Test listing questions."""
    # Create a question first
    client.post(
        "/api/questions",
        json={
            "title": "Test Question",
            "category": "技术",
            "difficulty": "medium",
        },
    )

    response = client.get("/api/questions")
    assert response.status_code == 200
    data = response.json()
    assert "questions" in data
    assert data["total"] >= 1


def test_create_session(client):
    """Test creating an interview session."""
    response = client.post(
        "/api/sessions",
        json={
            "title": "Python Interview",
            "job_role": "Python Developer",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Python Interview"
    assert data["status"] == "in_progress"


def test_create_bank(client):
    """Test creating a question bank."""
    response = client.post(
        "/api/banks",
        json={
            "name": "Python Basics",
            "description": "Basic Python questions",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Python Basics"
