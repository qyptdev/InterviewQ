"""API routes for questions."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional
import json
import csv
import io
from datetime import datetime

from app.models.schemas import (
    QuestionCreate,
    QuestionUpdate,
    QuestionResponse,
    QuestionGenerateRequest,
    QuestionGenerateResponse,
    QuestionBatchDeleteRequest,
    QuestionBatchExportRequest,
    QuestionBatchAddToBankRequest,
    QuestionBatchUpdateRequest,
)
from app.services.question_service import QuestionService
from app.models.db_models import QuestionDAO, QuestionBankDAO

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.post("", response_model=QuestionResponse)
async def create_question(question: QuestionCreate):
    """Create a new question."""
    result = QuestionService.create_question(
        title=question.title,
        category=question.category,
        difficulty=question.difficulty,
        tags=question.tags,
        expected_answer=question.expected_answer,
    )
    return result


@router.get("")
async def list_questions(
    category: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
):
    """List questions with filters and pagination."""
    return QuestionService.list_questions(category, difficulty, search, page, page_size)


@router.get("/{question_id}", response_model=QuestionResponse)
async def get_question(question_id: int):
    """Get a question by ID."""
    question = QuestionService.get_question(question_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目未找到")
    return question


@router.put("/{question_id}", response_model=QuestionResponse)
async def update_question(question_id: int, question: QuestionUpdate):
    """Update a question."""
    result = QuestionService.update_question(
        question_id,
        title=question.title,
        category=question.category,
        difficulty=question.difficulty,
        tags=question.tags,
        expected_answer=question.expected_answer,
    )
    if not result:
        raise HTTPException(status_code=404, detail="题目未找到")
    return result


@router.delete("/{question_id}")
async def delete_question(question_id: int):
    """Delete a question."""
    success = QuestionService.delete_question(question_id)
    if not success:
        raise HTTPException(status_code=404, detail="题目未找到")
    return {"message": "删除成功"}


@router.post("/generate", response_model=QuestionGenerateResponse)
async def generate_questions(request: QuestionGenerateRequest):
    """Generate questions using AI."""
    try:
        questions = await QuestionService.generate_questions(
            category=request.category,
            difficulty=request.difficulty,
            count=request.count,
            topic=request.topic,
            language=request.language,
        )
        return {"questions": questions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 生成失败: {str(e)}")


@router.post("/batch/delete")
async def batch_delete_questions(request: QuestionBatchDeleteRequest):
    """Batch delete questions."""
    if not request.question_ids:
        raise HTTPException(status_code=400, detail="未提供题目ID")

    try:
        deleted = QuestionDAO.batch_delete(request.question_ids)
        return {"message": f"成功删除 {deleted} 道题目", "deleted": deleted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量删除失败: {str(e)}")


@router.post("/batch/export")
async def batch_export_questions(request: QuestionBatchExportRequest):
    """Batch export questions."""
    if not request.question_ids:
        raise HTTPException(status_code=400, detail="未提供题目ID")

    try:
        questions = QuestionDAO.get_multiple(request.question_ids)
        timestamp = datetime.now().strftime("%Y%m%d")

        if request.format == "json":
            # Export as JSON
            content = json.dumps(questions, ensure_ascii=False, indent=2)
            media_type = "application/json"
            filename = f"questions_export_{timestamp}.json"
        else:
            # Export as CSV
            output = io.StringIO()
            if questions:
                fieldnames = ["id", "title", "category", "difficulty", "tags", "expected_answer", "created_at"]
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                for q in questions:
                    writer.writerow({k: q.get(k, "") for k in fieldnames})

            content = output.getvalue()
            media_type = "text/csv"
            filename = f"questions_export_{timestamp}.csv"

        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量导出失败: {str(e)}")


@router.post("/batch/add-to-bank")
async def batch_add_to_bank(request: QuestionBatchAddToBankRequest):
    """Batch add questions to a bank."""
    if not request.question_ids:
        raise HTTPException(status_code=400, detail="未提供题目ID")

    # Verify bank exists
    bank = QuestionBankDAO.get_by_id(request.bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")

    try:
        added = QuestionBankDAO.add_questions(request.bank_id, request.question_ids)
        return {
            "message": f"成功添加 {added} 道题目到题库 '{bank['name']}'",
            "added": added,
            "bank_id": request.bank_id,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量添加失败: {str(e)}")


@router.patch("/batch/update")
async def batch_update_questions(request: QuestionBatchUpdateRequest):
    """Batch update question properties."""
    if not request.question_ids:
        raise HTTPException(status_code=400, detail="未提供题目ID")

    try:
        updated = QuestionDAO.batch_update(
            question_ids=request.question_ids,
            category=request.category,
            difficulty=request.difficulty,
            tags_to_add=request.tags_to_add,
            tags_to_remove=request.tags_to_remove,
        )
        return {"message": f"成功更新 {updated} 道题目", "updated": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量更新失败: {str(e)}")
