"""API routes for interview sessions."""

import json
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional

from app.models.schemas import (
    SessionCreate,
    SessionResponse,
    AnswerSubmit,
    SessionUpdateRequest,
    SessionBatchDeleteRequest,
    SessionBatchExportRequest,
    SessionBatchTagsRequest,
    DraftSaveRequest,
    QuestionBookmarkRequest,
    QuestionNoteRequest,
    QuestionTimeRequest,
)
from app.services.interview_engine import InterviewEngine
from app.services.statistics_service import StatisticsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse)
async def create_session(session: SessionCreate):
    """Create a new interview session."""
    result = InterviewEngine.create_session(
        title=session.title, job_role=session.job_role
    )
    return result


@router.get("")
async def list_sessions(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List interview sessions."""
    return InterviewEngine.list_sessions(status, page, page_size)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: int):
    """Get a session by ID."""
    session = InterviewEngine.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话未找到")
    return session


@router.post("/{session_id}/start")
async def start_session(session_id: int, question_ids: list[int]):
    """Start an interview session with selected questions."""
    try:
        result = InterviewEngine.start_session(session_id, question_ids)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{session_id}/answer")
async def submit_answer(session_id: int, answer: AnswerSubmit):
    """Submit an answer and get feedback (non-streaming)."""
    try:
        result = await InterviewEngine.submit_answer(session_id, answer.user_answer)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提交答案失败: {str(e)}")


@router.post("/{session_id}/answer/stream")
async def submit_answer_stream(session_id: int, answer: AnswerSubmit):
    """Submit an answer and stream feedback via SSE."""
    session = InterviewEngine.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话未找到")

    async def event_generator():
        # Send connection established
        yield f"event: connected\ndata: {json.dumps({'content': '已连接'})}\n\n"

        try:
            async for chunk in InterviewEngine.submit_answer_stream(
                session_id, answer.user_answer
            ):
                event_type = chunk.get("type", "token")
                if event_type == "token":
                    data = json.dumps({"content": chunk["content"]})
                    yield f"event: token\ndata: {data}\n\n"
                elif event_type == "done":
                    done_payload = {
                        "content": chunk["content"],
                        "score": chunk["score"],
                        "next_question": chunk.get("next_question"),
                        "session_completed": chunk.get(
                            "session_completed", False
                        ),
                    }
                    # 传递追问信息
                    if chunk.get("followup"):
                        done_payload["followup"] = chunk["followup"]
                    if chunk.get("show_followup_choice"):
                        done_payload["show_followup_choice"] = chunk["show_followup_choice"]
                    yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"
                elif event_type == "error":
                    data = json.dumps({"content": chunk["content"]})
                    yield f"event: error\ndata: {data}\n\n"
        except Exception as e:
            logger.error(f"SSE stream error: {e}")
            data = json.dumps({"content": "流式传输中断"})
            yield f"event: error\ndata: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{session_id}/stream")
async def stream_session(session_id: int):
    """SSE stream for interview session."""
    session = InterviewEngine.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话未找到")

    async def event_generator():
        # Send connection established
        data = json.dumps({"type": "connected", "content": "已连接"})
        yield f"data: {data}\n\n"

        # Get questions
        questions = InterviewEngine.get_session_questions(session_id)

        for iq in questions:
            # Send question
            data = json.dumps({
                "type": "question",
                "content": iq["question_text"]
            })
            yield f"data: {data}\n\n"

            # Wait for answer (simulated with heartbeat)
            data = json.dumps({"type": "thinking", "content": "等待回答..."})
            yield f"data: {data}\n\n"

            # If answered, send feedback
            if iq["user_answer"]:
                data = json.dumps({
                    "type": "feedback",
                    "content": iq["ai_feedback"] or ""
                })
                yield f"data: {data}\n\n"
                data = json.dumps({
                    "type": "score",
                    "content": str(iq["score"] or 0)
                })
                yield f"data: {data}\n\n"

            await asyncio.sleep(0.1)

        # Send done
        yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{session_id}/complete")
async def complete_session(session_id: int):
    """Complete an interview session."""
    try:
        result = InterviewEngine.complete_session(session_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{session_id}/questions")
async def get_session_questions(session_id: int):
    """Get all questions in a session."""
    questions = InterviewEngine.get_session_questions(session_id)
    return {"questions": questions}


@router.get("/{session_id}/stats")
async def get_session_stats(session_id: int):
    """Get session statistics."""
    stats = InterviewEngine.get_session_stats(session_id)
    return stats


@router.post("/{session_id}/pause")
async def pause_session(session_id: int):
    """Pause an interview session."""
    try:
        result = InterviewEngine.pause_session(session_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{session_id}/resume")
async def resume_session(session_id: int):
    """Resume a paused interview session."""
    try:
        result = InterviewEngine.resume_session(session_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{session_id}/skip")
async def skip_question(session_id: int):
    """Skip the current unanswered question."""
    try:
        result = InterviewEngine.skip_question(session_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{session_id}/questions/{question_id}/draft")
async def save_draft(session_id: int, question_id: int, draft: DraftSaveRequest):
    """Save answer draft for a question."""
    try:
        result = InterviewEngine.save_draft(session_id, question_id, draft.draft_text)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{session_id}/questions/{question_id}/bookmark")
async def bookmark_question(
    session_id: int, question_id: int, bookmark: QuestionBookmarkRequest
):
    """Bookmark or unbookmark a question."""
    try:
        result = InterviewEngine.bookmark_question(question_id, bookmark.bookmarked)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{session_id}/questions/{question_id}/note")
async def add_question_note(
    session_id: int, question_id: int, note: QuestionNoteRequest
):
    """Add or update note for a question."""
    try:
        result = InterviewEngine.add_question_note(question_id, note.note)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{session_id}/questions/{question_id}/time")
async def update_question_time(
    session_id: int, question_id: int, time: QuestionTimeRequest
):
    """Update time spent on a question."""
    try:
        result = InterviewEngine.update_question_time(question_id, time.time_spent)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{session_id}/statistics")
async def get_session_statistics(session_id: int):
    """Get detailed session statistics."""
    try:
        stats = StatisticsService.get_session_statistics(session_id)
        return stats
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{session_id}/statistics/time")
async def get_time_analysis(session_id: int):
    """Get time analysis for session questions."""
    try:
        analysis = StatisticsService.get_time_analysis(session_id)
        return analysis
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{session_id}/statistics/scores")
async def get_score_distribution(session_id: int):
    """Get score distribution analysis."""
    try:
        distribution = StatisticsService.get_score_distribution(session_id)
        return distribution
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{session_id}/statistics/category")
async def get_category_performance(session_id: int):
    """Get performance analysis by category."""
    try:
        performance = StatisticsService.get_category_performance(session_id)
        return performance
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{session_id}")
async def update_session_metadata(session_id: int, update: SessionUpdateRequest):
    """Update session tags and notes."""
    try:
        result = InterviewEngine.update_session_metadata(
            session_id, update.tags, update.notes
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{session_id}/restart", response_model=SessionResponse)
async def restart_session(session_id: int):
    """Restart a completed session by creating a new clone."""
    try:
        new_session = InterviewEngine.restart_session(session_id)
        return new_session
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重新开始失败: {str(e)}")


@router.post("/batch/delete")
async def batch_delete_sessions(request: SessionBatchDeleteRequest):
    """Batch delete sessions."""
    try:
        deleted = InterviewEngine.batch_delete_sessions(request.session_ids)
        return {"message": f"成功删除 {deleted} 个会话", "deleted": deleted}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量删除失败: {str(e)}")


@router.post("/batch/export")
async def batch_export_sessions(request: SessionBatchExportRequest):
    """Batch export sessions."""
    try:
        result = InterviewEngine.batch_export_sessions(
            request.session_ids, request.format
        )

        if result["format"] == "csv":
            from fastapi.responses import Response
            return Response(
                content=result["data"].encode("utf-8"),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="sessions_export.csv"'}
            )
        else:
            return result["data"]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量导出失败: {str(e)}")


@router.patch("/batch/tags")
async def batch_update_tags(request: SessionBatchTagsRequest):
    """Batch update session tags."""
    try:
        updated = InterviewEngine.batch_update_tags(
            request.session_ids,
            request.tags_to_add,
            request.tags_to_remove
        )
        return {"message": f"成功更新 {updated} 个会话的标签", "updated": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量标记失败: {str(e)}")


@router.put("/{session_id}/questions/{question_id}/answer")
async def edit_answer(session_id: int, question_id: int, answer: AnswerSubmit):
    """Edit an existing answer and stream new feedback via SSE."""
    session = InterviewEngine.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话未找到")

    async def event_generator():
        # Send connection established
        yield f"event: connected\ndata: {json.dumps({'content': '已连接'})}\n\n"

        try:
            async for chunk in InterviewEngine.edit_answer_stream(
                session_id, question_id, answer.user_answer
            ):
                event_type = chunk.get("type", "token")
                if event_type == "token":
                    data = json.dumps({"content": chunk["content"]})
                    yield f"event: token\ndata: {data}\n\n"
                elif event_type == "done":
                    done_payload = json.dumps({
                        "content": chunk["content"],
                        "score": chunk["score"],
                        "is_edit": chunk.get("is_edit", False),
                        "followup": chunk.get("followup"),
                    })
                    yield f"event: done\ndata: {done_payload}\n\n"
                elif event_type == "error":
                    data = json.dumps({"content": chunk["content"]})
                    yield f"event: error\ndata: {data}\n\n"
        except Exception as e:
            logger.error(f"SSE stream error during edit: {e}")
            data = json.dumps({"content": "流式传输中断"})
            yield f"event: error\ndata: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{session_id}/questions/{question_id}/skip")
async def skip_followup_question(session_id: int, question_id: int):
    """Skip a followup question."""
    try:
        result = InterviewEngine.skip_followup_question(session_id, question_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"跳过失败: {str(e)}")


