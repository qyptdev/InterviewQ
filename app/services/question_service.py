"""Question service for CRUD and generation."""

import logging
from typing import Optional

from app.models.db_models import QuestionDAO, QuestionBankDAO
from app.llm.router import generate_questions as llm_generate_questions

logger = logging.getLogger(__name__)


class QuestionService:
    """Service for question operations."""

    @staticmethod
    def create_question(title: str, category: str, difficulty: str, tags: str, expected_answer: str) -> dict:
        """Create a new question."""
        return QuestionDAO.create(title, category, difficulty, tags, expected_answer)

    @staticmethod
    def get_question(question_id: int) -> Optional[dict]:
        """Get a question by ID."""
        return QuestionDAO.get_by_id(question_id)

    @staticmethod
    def list_questions(
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List questions with pagination."""
        offset = (page - 1) * page_size
        questions = QuestionDAO.get_all(category, difficulty, search, page_size, offset)
        total = QuestionDAO.count(category, difficulty, search)
        return {
            "questions": questions,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @staticmethod
    def update_question(question_id: int, **kwargs) -> Optional[dict]:
        """Update a question."""
        return QuestionDAO.update(question_id, **kwargs)

    @staticmethod
    def delete_question(question_id: int) -> bool:
        """Delete a question."""
        return QuestionDAO.delete(question_id)

    @staticmethod
    async def generate_questions(
        category: str,
        difficulty: str,
        count: int,
        topic: str,
        language: str = "zh",
    ) -> list[dict]:
        """Generate questions using LLM and save to database."""
        try:
            generated = await llm_generate_questions(category, difficulty, count, topic, language)
            saved_questions = []
            for q in generated:
                question = QuestionDAO.create(
                    title=q.get("title", ""),
                    category=category,
                    difficulty=difficulty,
                    tags=q.get("tags", topic),
                    expected_answer=q.get("expected_answer", ""),
                )
                saved_questions.append(question)
            return saved_questions
        except Exception as e:
            logger.error(f"Question generation failed: {e}")
            raise
