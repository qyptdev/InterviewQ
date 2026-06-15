"""API routes for resume upload and intelligent question generation.

Supports multiple input modes:
- Job title + JD only (no resume file)
- Resume file only (job title required)
- Resume file + Job title + JD (recommended for best results)
"""

import json as json_module
import logging

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.schemas import ResumeGenerateResponse, ResumeSections
from app.models.db_models import QuestionGenerationHistoryDAO
from app.services.question_generator import (
    parse_uploaded_file,
    process_resume_and_generate,
    create_generation_job,
    stream_job_events,
)
from app.services.generation_job import generation_registry
from app.services.document_parser import extract_resume_sections, ai_extract_resume_sections

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resume", tags=["resume"])


class ParseTextRequest(BaseModel):
    """Request model for parsing resume text."""
    text: str
    filename: str = "resume.txt"


@router.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    """Upload a resume file and extract text + sections.

    Supports: .txt, .md, .pdf, .docx
    """
    try:
        content = await file.read()
        text = await parse_uploaded_file(file.filename, content)
        sections = extract_resume_sections(text)

        return {
            "filename": file.filename,
            "text_length": len(text),
            "sections": sections,
            "parse_method": "fixed",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Resume upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"简历上传失败: {str(e)}")


@router.post("/ai-parse")
async def ai_parse_resume(file: UploadFile = File(...)):
    """Upload a resume file and use AI to extract sections intelligently.

    Supports: .txt, .md, .pdf, .docx
    """
    try:
        content = await file.read()
        text = await parse_uploaded_file(file.filename, content)
        sections = await ai_extract_resume_sections(text)

        return {
            "filename": file.filename,
            "text_length": len(text),
            "sections": sections,
            "parse_method": "ai",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"AI resume parse failed: {e}")
        raise HTTPException(status_code=500, detail=f"AI 解析失败: {str(e)}")


@router.post("/parse-text")
async def parse_text(request: ParseTextRequest):
    """Parse resume text directly (for cached resume text).

    Args:
        request: ParseTextRequest with text and optional filename.

    Returns:
        Parsed sections dict.
    """
    try:
        if not request.text or not request.text.strip():
            raise HTTPException(status_code=400, detail="简历文本不能为空")

        # Use fixed parsing for cached text
        sections = extract_resume_sections(request.text)

        return {
            "filename": request.filename,
            "text_length": len(request.text),
            "sections": sections,
            "parse_method": "fixed",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Text parsing failed: {e}")
        raise HTTPException(status_code=500, detail=f"文本解析失败: {str(e)}")


@router.post("/generate", response_model=ResumeGenerateResponse)
async def generate_from_resume(
    file: UploadFile = File(...),
    job_title: str = Form(default=""),
    jd_text: str = Form(default=""),
    question_count: int = Form(default=10, ge=1, le=500),
    bank_name: str = Form(default=""),
    edited_sections: str = Form(default=""),
):
    """Upload resume + optional JD, generate interview questions, save to a new bank.

    Full pipeline: parse resume -> extract sections -> LLM generate -> save to bank.

    Args:
        file: Resume file (PDF/Word/Markdown/Text).
        job_title: Target job title (required for relevant questions).
        jd_text: Job description text (optional).
        question_count: Number of questions to generate (1-50).
        bank_name: Custom bank name (optional, auto-generated if empty).
        edited_sections: JSON string of user-edited resume sections (optional).
    """
    try:
        content = await file.read()

        # If user provided edited sections, use them
        sections_override = None
        if edited_sections:
            try:
                sections_override = json_module.loads(edited_sections)
            except json_module.JSONDecodeError as e:
                logger.warning(f"Failed to parse edited_sections JSON, ignoring override: {e}")

        result = await process_resume_and_generate(
            filename=file.filename,
            content=content,
            jd_text=jd_text,
            job_title=job_title,
            question_count=question_count,
            bank_name=bank_name if bank_name else None,
            sections_override=sections_override,
        )

        return ResumeGenerateResponse(
            bank_id=result["bank"]["id"],
            bank_name=result["bank"]["name"],
            questions_saved=result["questions_saved"],
            resume_sections=ResumeSections(**result["resume_sections"]),
            questions=result["questions"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Resume question generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"题目生成失败: {str(e)}")


@router.post("/generate-stream")
async def generate_from_resume_stream(
    file: UploadFile = File(None),
    job_title: str = Form(default=""),
    jd_text: str = Form(default=""),
    question_count: int = Form(default=10, ge=1, le=500),
    bank_name: str = Form(default=""),
    edited_sections: str = Form(default=""),
    generation_mode: str = Form(default="standard"),
    concurrency: int = Form(default=0, ge=0),
    batch_size: int = Form(default=0, ge=0),
):
    """Generate interview questions via SSE streaming (flexible input modes).

    Supports multiple input modes:
    - Mode 1: Job title + JD (no resume file)
    - Mode 2: Resume file + Job title
    - Mode 3: Resume file + Job title + JD (recommended)

    At least one of the following must be provided:
    - Resume file
    - Job title with optional JD

    Generation modes:
    - fast: Quick generation with basic quality
    - standard: Balanced speed and quality (default)
    - deep: High-quality output with strict validation

    Advanced params (0 = use mode defaults):
    - concurrency: Max concurrent batch generation (1-5)
    - batch_size: Questions per LLM call (3-10)

    Each generated question is pushed to the frontend immediately via SSE.
    The first SSE event is ``job_started`` containing ``job_id`` for reconnect.
    When all questions are done, a final 'complete' event is sent with bank info.
    """
    # Validate generation mode
    from app.config import GENERATION_MODES, get_generation_mode_config
    if generation_mode not in GENERATION_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid generation_mode: {generation_mode}. Must be one of: {', '.join(GENERATION_MODES.keys())}",
        )

    # Validate input: at least file or job_title must be provided
    has_file = file and file.filename
    has_job_title = job_title and job_title.strip()

    if not has_file and not has_job_title:
        raise HTTPException(
            status_code=400,
            detail="请至少上传简历文件或填写岗位名称",
        )

    # Resolve concurrency / batch_size: 0 means "use mode recommendation"
    mode_cfg = get_generation_mode_config(generation_mode)
    effective_concurrency = concurrency if concurrency > 0 else mode_cfg.get("recommended_concurrency", 1)
    effective_batch_size = batch_size if batch_size > 0 else None  # None = use plan default

    try:
        content = await file.read() if has_file else b""

        sections_override = None
        if edited_sections:
            try:
                sections_override = json_module.loads(edited_sections)
            except json_module.JSONDecodeError as e:
                logger.warning(f"Failed to parse edited_sections JSON in stream endpoint, ignoring override: {e}")

        # Create an independent job (not tied to request lifecycle)
        job = create_generation_job(
            filename=file.filename if has_file else "",
            content=content,
            jd_text=jd_text,
            job_title=job_title,
            question_count=question_count,
            bank_name=bank_name if bank_name else None,
            sections_override=sections_override,
            generation_mode=generation_mode,
            concurrency=effective_concurrency,
            custom_batch_size=effective_batch_size,
        )

        async def event_stream():
            # First event: job_started so client knows the job_id
            yield f"data: {json_module.dumps({'type': 'job_started', 'job_id': job.job_id}, ensure_ascii=False)}\n\n"
            async for event_data in stream_job_events(job):
                yield f"data: {json_module.dumps(event_data, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Resume stream generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"题目生成失败: {str(e)}")


@router.get("/history")
async def get_generation_history(
    search: str = "",
    limit: int = 20,
    offset: int = 0,
):
    """Get question generation history with optional search.

    Args:
        search: Search keyword (matches job_title or resume_filename).
        limit: Maximum number of records to return (default 20).
        offset: Number of records to skip (default 0).

    Returns:
        {
            "total": int,
            "items": [
                {
                    "id": int,
                    "job_title": str,
                    "jd_text": str,
                    "resume_filename": str,
                    "resume_text": str,
                    "question_count": int,
                    "bank_id": int,
                    "bank_name": str,
                    "generation_mode": str,
                    "created_at": str
                }
            ]
        }
    """
    try:
        total = QuestionGenerationHistoryDAO.count(search=search if search else None)
        items = QuestionGenerationHistoryDAO.get_all(
            search=search if search else None,
            limit=limit,
            offset=offset,
        )
        return {"total": total, "items": items}
    except Exception as e:
        logger.error(f"Failed to fetch generation history: {e}")
        raise HTTPException(status_code=500, detail=f"获取历史记录失败: {str(e)}")


@router.get("/history/{history_id}")
async def get_history_detail(history_id: int):
    """Get a single history record by ID.

    Args:
        history_id: History record ID.

    Returns:
        History record dict or 404 if not found.
    """
    try:
        history = QuestionGenerationHistoryDAO.get_by_id(history_id)
        if not history:
            raise HTTPException(status_code=404, detail="历史记录不存在")
        return history
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch history detail: {e}")
        raise HTTPException(status_code=500, detail=f"获取历史记录详情失败: {str(e)}")


@router.delete("/history/{history_id}")
async def delete_history(history_id: int):
    """Delete a history record by ID.

    Args:
        history_id: History record ID.

    Returns:
        {"success": true} or 404 if not found.
    """
    try:
        success = QuestionGenerationHistoryDAO.delete(history_id)
        if not success:
            raise HTTPException(status_code=404, detail="历史记录不存在")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete history: {e}")
        raise HTTPException(status_code=500, detail=f"删除历史记录失败: {str(e)}")


# ---------------------------------------------------------------------------
# Generation job control endpoints
# ---------------------------------------------------------------------------


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    """Pause a running generation job.

    The generation loop will block until resumed. Already-generated
    questions and progress are preserved in memory.
    """
    job = generation_registry.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status != "running":
        raise HTTPException(status_code=400, detail=f"任务状态为 {job.status}，无法暂停")

    job.pause_event.clear()
    job.status = "paused"
    job.push_event({"type": "stage", "stage": "paused", "message": "生成已暂停"})
    logger.info(f"Job {job_id} paused")
    return {"status": "ok"}


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    """Resume a paused generation job."""
    job = generation_registry.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status != "paused":
        raise HTTPException(status_code=400, detail=f"任务状态为 {job.status}，无法恢复")

    job.status = "running"
    job.pause_event.set()
    job.push_event({"type": "stage", "stage": "resumed", "message": "生成已恢复"})
    logger.info(f"Job {job_id} resumed")
    return {"status": "ok"}


@router.post("/jobs/{job_id}/terminate")
async def terminate_job(job_id: str):
    """Terminate a generation job.

    Already-generated questions are saved to the question bank before
    the job is cleaned up. This is a graceful shutdown — the running
    generation loop detects the flag and persists partial results.
    """
    job = generation_registry.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status in ("completed", "terminated", "error"):
        raise HTTPException(status_code=400, detail=f"任务已结束（状态: {job.status}）")

    # If paused, wake it up so the loop can observe terminate_flag
    if job.status == "paused":
        job.pause_event.set()

    job.terminate_flag = True
    logger.info(f"Job {job_id} terminate requested")
    return {"status": "ok"}


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    """SSE reconnect endpoint for a running generation job.

    Replays all past events then streams new ones as they arrive.
    """
    job = generation_registry.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_stream():
        async for event_data in stream_job_events(job):
            yield f"data: {json_module.dumps(event_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    """Get the current status and progress of a generation job."""
    job = generation_registry.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "job_id": job.job_id,
        "status": job.status,
        "bank_name": job.bank_name,
        "bank_id": job.bank_id,
        "total_planned": job.total_planned,
        "completed_count": job.completed_count,
        "current_stage": job.current_stage,
        "error_message": job.error_message,
        "generation_params": job.generation_params,
    }
