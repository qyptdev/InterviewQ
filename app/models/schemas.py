"""Pydantic schemas for request/response models."""

from pydantic import BaseModel, Field
from typing import Optional

from app.config import MAX_QUESTION_COUNT


# === Question Schemas ===

class QuestionCreate(BaseModel):
    """Schema for creating a question."""
    title: str = Field(..., min_length=1, max_length=2000)
    category: str = Field(default="技术", max_length=50)
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    tags: str = Field(default="", max_length=500)
    expected_answer: str = Field(default="", max_length=10000)


class QuestionUpdate(BaseModel):
    """Schema for updating a question."""
    title: Optional[str] = Field(None, min_length=1, max_length=2000)
    category: Optional[str] = Field(None, max_length=50)
    difficulty: Optional[str] = Field(None, pattern="^(easy|medium|hard)$")
    tags: Optional[str] = Field(None, max_length=500)
    expected_answer: Optional[str] = Field(None, max_length=10000)


class QuestionResponse(BaseModel):
    """Schema for question response."""
    id: int
    title: str
    category: str
    difficulty: str
    tags: str
    expected_answer: str
    created_at: str
    updated_at: str


class QuestionGenerateRequest(BaseModel):
    """Schema for AI question generation request."""
    category: str = Field(default="技术", max_length=50)
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    count: int = Field(default=5, ge=1, le=20)
    topic: str = Field(default="", max_length=200)
    language: str = Field(default="zh", max_length=10)


class QuestionGenerateResponse(BaseModel):
    """Schema for AI question generation response."""
    questions: list[QuestionResponse]


# === Interview Session Schemas ===

class SessionCreate(BaseModel):
    """Schema for creating an interview session."""
    title: str = Field(..., min_length=1, max_length=200)
    job_role: str = Field(default="", max_length=200)


class SessionResponse(BaseModel):
    """Schema for session response."""
    id: int
    title: str
    job_role: str
    status: str
    created_at: str
    completed_at: Optional[str] = None
    paused_at: Optional[str] = None
    tags: str = ""
    notes: str = ""
    total_questions: Optional[int] = None


class SessionPauseRequest(BaseModel):
    """Schema for pausing a session."""
    pass  # No additional data needed


class SessionUpdateRequest(BaseModel):
    """Schema for updating session metadata."""
    tags: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=5000)


class SessionRestartRequest(BaseModel):
    """Request to restart a completed session."""
    pass  # session_id is in the URL path


class SessionBatchDeleteRequest(BaseModel):
    """Request to batch delete sessions."""
    session_ids: list[int]


class SessionBatchExportRequest(BaseModel):
    """Request to batch export sessions."""
    session_ids: list[int]
    format: str = Field(default="json", pattern="^(json|csv)$")


class SessionBatchTagsRequest(BaseModel):
    """Request to batch update tags."""
    session_ids: list[int]
    tags_to_add: list[str] = Field(default_factory=list)
    tags_to_remove: list[str] = Field(default_factory=list)


class AnswerSubmit(BaseModel):
    """Schema for submitting an answer."""
    user_answer: str = Field(..., min_length=1, max_length=10000)


class AnswerFeedback(BaseModel):
    """Schema for answer feedback."""
    feedback: str
    score: float = Field(ge=0, le=100)
    next_question: Optional[str] = None
    session_completed: bool = False


# === Interview Question Schemas ===

class InterviewQuestionResponse(BaseModel):
    """Schema for interview question in a session."""
    id: int
    session_id: int
    question_id: Optional[int] = None
    question_text: str
    user_answer: Optional[str] = None
    ai_feedback: Optional[str] = None
    score: Optional[float] = None
    order_index: int
    created_at: str
    answered_at: Optional[str] = None
    draft_answer: Optional[str] = None
    time_spent: int = 0
    is_bookmarked: bool = False
    notes: str = ""


class DraftSaveRequest(BaseModel):
    """Schema for saving answer draft."""
    draft_text: str = Field(..., max_length=10000)


class QuestionBookmarkRequest(BaseModel):
    """Schema for bookmarking a question."""
    bookmarked: bool


class QuestionNoteRequest(BaseModel):
    """Schema for adding notes to a question."""
    note: str = Field(..., max_length=5000)


class QuestionTimeRequest(BaseModel):
    """Schema for updating question time spent."""
    time_spent: int = Field(..., ge=0, description="Time spent in seconds")


# === Question Bank Schemas ===

class BankCreate(BaseModel):
    """Schema for creating a question bank."""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)


class BankResponse(BaseModel):
    """Schema for bank response."""
    id: int
    name: str
    description: str
    created_at: str
    question_count: int = 0


class BankImportRequest(BaseModel):
    """Schema for importing questions to a bank."""
    question_ids: list[int]


class BankUpdate(BaseModel):
    """Schema for updating a question bank."""
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)


class BatchRemoveRequest(BaseModel):
    """Schema for batch removing questions from a bank."""
    question_ids: list[int]


class CloneBankRequest(BaseModel):
    """Schema for cloning a question bank."""
    name: Optional[str] = None
    description: Optional[str] = None


class BankStatistics(BaseModel):
    """Schema for bank statistics response."""
    total: int
    by_category: dict[str, int]
    by_difficulty: dict[str, int]


class BankBatchDeleteRequest(BaseModel):
    """Schema for batch deleting question banks."""
    bank_ids: list[int]


class BankBatchExportRequest(BaseModel):
    """Schema for batch exporting question banks."""
    bank_ids: list[int]
    format: str = Field(default="json", pattern="^(json|csv)$")


class BankBatchCloneRequest(BaseModel):
    """Schema for batch cloning question banks."""
    bank_ids: list[int]
    name_suffix: str = Field(default=" - 副本", max_length=50)


class QuestionBatchDeleteRequest(BaseModel):
    """Schema for batch deleting questions."""
    question_ids: list[int]


class QuestionBatchExportRequest(BaseModel):
    """Schema for batch exporting questions."""
    question_ids: list[int]
    format: str = Field(default="json", pattern="^(json|csv)$")


class QuestionBatchAddToBankRequest(BaseModel):
    """Schema for batch adding questions to a bank."""
    question_ids: list[int]
    bank_id: int


class QuestionBatchUpdateRequest(BaseModel):
    """Schema for batch updating question properties."""
    question_ids: list[int]
    category: Optional[str] = None
    difficulty: Optional[str] = None
    tags_to_add: list[str] = Field(default_factory=list)
    tags_to_remove: list[str] = Field(default_factory=list)


# === Resume / Question Generation Schemas ===

class ResumeGenerateRequest(BaseModel):
    """Schema for resume-based question generation request."""
    jd_text: str = Field(
        default="", max_length=20000, description="职位描述（可选）"
    )
    question_count: int = Field(
        default=10, ge=1, le=MAX_QUESTION_COUNT,
        description="生成题目数量"
    )
    bank_name: str = Field(
        default="", max_length=200, description="题库名称（可选，自动生成）"
    )


class ResumeSections(BaseModel):
    """Schema for extracted resume sections."""
    basic_info: str = Field(default="", description="基本信息（姓名、联系方式等）")
    education: str = Field(default="", description="教育经历")
    skills: str = Field(default="", description="专业技能")
    experience: str = Field(default="", description="工作经验")
    projects: str = Field(default="", description="项目经历")
    summary: str = Field(default="", description="个人简介")
    other: str = Field(default="", description="其他信息")


class ResumeGenerateResponse(BaseModel):
    """Schema for resume-based question generation response."""
    bank_id: int
    bank_name: str
    questions_saved: int
    resume_sections: ResumeSections
    questions: list[dict]


# === Document Schemas ===

class DocumentUploadResponse(BaseModel):
    """Schema for document upload response."""
    id: int
    filename: str
    file_type: str
    created_at: str


class DocumentResponse(BaseModel):
    """Schema for document response."""
    id: int
    filename: str
    file_type: str
    created_at: str


# === Health Check ===

class HealthResponse(BaseModel):
    """Schema for health check response."""
    status: str = "ok"
    version: str = "1.0.0"
    database: str = "connected"
    llm_provider: str = "configured"
