"""FastAPI application entry point."""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.database import init_db, close_db
from app.models.schemas import HealthResponse

# Configure logging
settings = get_settings()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "default")

if LOG_FORMAT == "json":
    logging.basicConfig(
        level=LOG_LEVEL,
        format='{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}',
    )
else:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

logger = logging.getLogger("interviewq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info(f"Application starting — env={settings.app_env}")
    if not settings.app_secret_key:
        logger.warning(
            "APP_SECRET_KEY is not set — sessions will not be securely signed. "
            "Set APP_SECRET_KEY in .env for production."
        )
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Application shutting down")
    close_db()


app = FastAPI(
    title="InterviewQ - AI Interview Agent",
    description="AI-powered interview question generator and simulator",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="app/templates")

# Add get_settings to template globals for config access
templates.env.globals["get_settings"] = get_settings

# Add format_time filter for friendly time display
def format_time_filter(seconds):
    """Format seconds into friendly time string like '1h 23m 45s' or '5m 30s' or '45s'."""
    if not seconds or seconds <= 0:
        return "0s"
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    if hrs > 0:
        return f"{hrs}h {mins}m {secs}s"
    elif mins > 0:
        return f"{mins}m {secs}s"
    else:
        return f"{secs}s"

templates.env.filters["format_time"] = format_time_filter

# Include API routes
from app.api.routes_questions import router as questions_router
from app.api.routes_sessions import router as sessions_router
from app.api.routes_banks import router as banks_router
from app.api.routes_docs import router as docs_router
from app.api.routes_resume import router as resume_router

app.include_router(questions_router)
app.include_router(sessions_router)
app.include_router(banks_router)
app.include_router(docs_router)
app.include_router(resume_router)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Dashboard page."""
    from app.models.db_models import QuestionDAO, SessionDAO, QuestionBankDAO

    question_count = QuestionDAO.count()
    session_count = len(SessionDAO.get_all(limit=1000))
    bank_count = len(QuestionBankDAO.get_all(limit=1000))

    # Get recent sessions
    all_sessions = SessionDAO.get_all(limit=100)
    recent_sessions = all_sessions[:5] if all_sessions else []

    # Get pending sessions (in_progress)
    pending_sessions = [s for s in all_sessions if s.get('status') == 'in_progress'][:5]

    # Get recent banks
    recent_banks = QuestionBankDAO.get_all(limit=5)

    # Calculate question stats by category
    all_questions = QuestionDAO.get_all(limit=10000)
    stats = {
        'technical': len([q for q in all_questions if q.get('category') == '技术']),
        'behavioral': len([q for q in all_questions if q.get('category') == '行为']),
        'system_design': len([q for q in all_questions if q.get('category') == '系统设计']),
        'hr': len([q for q in all_questions if q.get('category') == 'HR']),
    }

    return templates.TemplateResponse(
        request,
        "index.html",
        context={
            "question_count": question_count,
            "session_count": session_count,
            "bank_count": bank_count,
            "recent_sessions": recent_sessions,
            "recent_banks": recent_banks,
            "pending_sessions": pending_sessions,
            "stats": stats,
        },
    )


@app.get("/questions", response_class=HTMLResponse)
async def questions_page(request: Request):
    """Redirect to unified banks page with all questions tab."""
    return RedirectResponse(url="/banks?tab=all", status_code=301)


@app.get("/questions/new", response_class=HTMLResponse)
async def new_question_page(request: Request):
    """New question form page."""
    return templates.TemplateResponse(request, "questions/form.html", context={"question": None})


@app.get("/questions/{question_id}", response_class=HTMLResponse)
async def question_detail_page(request: Request, question_id: int):
    """Question detail page."""
    from app.models.db_models import QuestionDAO

    question = QuestionDAO.get_by_id(question_id)
    if not question:
        return templates.TemplateResponse(
            request,
            "questions/detail.html",
            context={"question": None, "error": "题目未找到"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "questions/detail.html",
        context={"question": question},
    )


@app.get("/questions/{question_id}/edit", response_class=HTMLResponse)
async def edit_question_page(request: Request, question_id: int):
    """Edit question form page."""
    from app.models.db_models import QuestionDAO

    question = QuestionDAO.get_by_id(question_id)
    if not question:
        return templates.TemplateResponse(
            request,
            "questions/form.html",
            context={"question": None, "error": "题目未找到"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "questions/form.html",
        context={"question": question},
    )


@app.get("/sessions", response_class=HTMLResponse)
async def sessions_page(request: Request):
    """Sessions list page."""
    from app.models.db_models import SessionDAO

    sessions = SessionDAO.get_all(limit=100)
    return templates.TemplateResponse(
        request,
        "sessions/list.html",
        context={"sessions": sessions},
    )


@app.get("/sessions/new", response_class=HTMLResponse)
async def new_session_page(request: Request):
    """New session form page."""
    return templates.TemplateResponse(request, "sessions/new.html")


@app.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_detail_page(request: Request, session_id: int):
    """Session detail/chat page."""
    from app.models.db_models import SessionDAO, InterviewQuestionDAO

    session = SessionDAO.get_by_id(session_id)
    if not session:
        return templates.TemplateResponse(
            request,
            "sessions/chat.html",
            context={"session": None, "questions": [], "error": "会话未找到"},
            status_code=404,
        )
    questions = InterviewQuestionDAO.get_by_session(session_id)
    return templates.TemplateResponse(
        request,
        "sessions/chat.html",
        context={"session": session, "questions": questions},
    )


@app.get("/sessions/{session_id}/practice", response_class=HTMLResponse)
async def session_practice_page(request: Request, session_id: int):
    """Session practice page with card layout."""
    from app.models.db_models import SessionDAO, InterviewQuestionDAO

    session = SessionDAO.get_by_id(session_id)
    if not session:
        return templates.TemplateResponse(
            request,
            "sessions/practice.html",
            context={"session": None, "questions": [], "error": "会话未找到"},
            status_code=404,
        )
    questions = InterviewQuestionDAO.get_by_session(session_id)
    return templates.TemplateResponse(
        request,
        "sessions/practice.html",
        context={"session": session, "questions": questions},
    )


@app.get("/sessions/{session_id}/review", response_class=HTMLResponse)
async def session_review_page(request: Request, session_id: int):
    """Session review page."""
    from app.models.db_models import SessionDAO, InterviewQuestionDAO

    session = SessionDAO.get_by_id(session_id)
    if not session:
        return templates.TemplateResponse(
            request,
            "sessions/review.html",
            context={"session": None, "questions": [], "error": "会话未找到"},
            status_code=404,
        )
    questions = InterviewQuestionDAO.get_by_session(session_id)

    # Calculate stats
    answered = [q for q in questions if q["user_answer"]]
    scores = [q["score"] for q in answered if q["score"] is not None]
    avg_score = sum(scores) / len(scores) if scores else 0

    return templates.TemplateResponse(
        request,
        "sessions/review.html",
        context={
            "session": session,
            "questions": questions,
            "stats": {
                "total": len(questions),
                "answered": len(answered),
                "average_score": round(avg_score, 1),
            },
        },
    )


@app.get("/banks", response_class=HTMLResponse)
async def banks_page(
    request: Request,
    tab: str = "banks",
    page: int = 1,
    search: Optional[str] = None,
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
):
    """Unified banks page with tabs for 'my banks' and 'all questions'."""
    from app.models.db_models import QuestionBankDAO, QuestionDAO

    banks = QuestionBankDAO.get_all(limit=500)
    total_banks = QuestionBankDAO.count_all()

    # Pagination for all questions tab with filters
    page_size = 100
    offset = (page - 1) * page_size
    questions = QuestionDAO.get_all(
        category=category,
        difficulty=difficulty,
        search=search,
        limit=page_size,
        offset=offset,
    )
    total_questions = QuestionDAO.count(category=category, difficulty=difficulty, search=search)
    total_pages = (total_questions + page_size - 1) // page_size if total_questions > 0 else 1

    return templates.TemplateResponse(
        request,
        "banks/list.html",
        context={
            "banks": banks,
            "questions": questions,
            "total_banks": total_banks,
            "total_questions": total_questions,
            "active_tab": tab,
            "page": page,
            "total_pages": total_pages,
            "page_size": page_size,
        },
    )


@app.get("/banks/{bank_id}", response_class=HTMLResponse)
async def bank_detail_page(request: Request, bank_id: int, page: int = 1):
    """Question bank detail page with paginated questions."""
    from app.models.db_models import QuestionBankDAO

    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        return templates.TemplateResponse(
            request,
            "banks/detail.html",
            context={"bank": None, "questions": [], "error": "题库未找到"},
            status_code=404,
        )

    page_size = 20
    offset = (page - 1) * page_size
    questions = QuestionBankDAO.get_questions(bank_id, limit=page_size, offset=offset)
    total_count = QuestionBankDAO.count_questions(bank_id)
    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

    return templates.TemplateResponse(
        request,
        "banks/detail.html",
        context={
            "bank": bank,
            "questions": questions,
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
        },
    )


@app.get("/resume", response_class=HTMLResponse)
async def resume_page(request: Request):
    """Resume upload and question generation page."""
    return templates.TemplateResponse(request, "resume/upload.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=True)
