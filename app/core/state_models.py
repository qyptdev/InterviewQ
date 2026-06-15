"""Pydantic state models for agent orchestration."""

from pydantic import BaseModel, Field
from typing import Optional


class QuestionPlan(BaseModel):
    """Plan for question generation."""
    job_title: str = Field(default="", description="Target job title")
    resume_summary: str = Field(default="", description="Summary of the resume")
    jd_requirements: str = Field(default="", description="Job description requirements")
    rag_context: str = Field(default="", description="Retrieved RAG context chunks concatenated")
    question_types: list[str] = Field(default_factory=list, description="Types of questions to generate")
    difficulty_distribution: dict[str, int] = Field(
        default_factory=lambda: {"easy": 2, "medium": 3, "hard": 1},
        description="Distribution of difficulty levels"
    )
    total_batches: int = Field(default=1, description="Number of batches to generate")
    batch_size: int = Field(default=5, description="Questions per batch")
    concurrency: int = Field(default=1, description="Max concurrent batch generation (1=sequential)")


class QuestionBatch(BaseModel):
    """A batch of generated questions."""
    batch_index: int
    questions: list[dict]
    status: str = "pending"  # pending, generated, validated, failed


class ValidationResult(BaseModel):
    """Result of question validation."""
    is_valid: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class InterviewState(BaseModel):
    """State for interview session."""
    session_id: int
    current_question_index: int = 0
    questions_pool: list[dict] = Field(default_factory=list)
    answers: list[dict] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)
    total_score: float = 0.0
    status: str = "waiting"  # waiting, in_progress, completed
