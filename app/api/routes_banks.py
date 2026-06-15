"""API routes for question banks."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional
import json
import csv
import io
from datetime import datetime

from app.models.schemas import (
    BankCreate,
    BankResponse,
    BankImportRequest,
    BankUpdate,
    BatchRemoveRequest,
    CloneBankRequest,
    BankStatistics,
    BankBatchDeleteRequest,
    BankBatchExportRequest,
    BankBatchCloneRequest,
)
from app.models.db_models import QuestionBankDAO

router = APIRouter(prefix="/api/banks", tags=["banks"])


@router.post("", response_model=BankResponse)
async def create_bank(bank: BankCreate):
    """Create a new question bank."""
    result = QuestionBankDAO.create(name=bank.name, description=bank.description)
    return result


@router.get("")
async def list_banks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
):
    """List question banks."""
    offset = (page - 1) * page_size
    banks = QuestionBankDAO.get_all(page_size, offset)
    return {"banks": banks, "page": page, "page_size": page_size}


@router.get("/{bank_id}", response_model=BankResponse)
async def get_bank(bank_id: int):
    """Get a question bank by ID."""
    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")
    return bank


@router.delete("/{bank_id}")
async def delete_bank(bank_id: int):
    """Delete a question bank."""
    success = QuestionBankDAO.delete(bank_id)
    if not success:
        raise HTTPException(status_code=404, detail="题库未找到")
    return {"message": "删除成功"}


@router.post("/{bank_id}/import")
async def import_questions(bank_id: int, request: BankImportRequest):
    """Import questions into a bank."""
    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")

    added = QuestionBankDAO.add_questions(bank_id, request.question_ids)
    return {"message": f"成功导入 {added} 道题目", "added": added}


@router.get("/{bank_id}/questions")
async def get_bank_questions(bank_id: int):
    """Get all questions in a bank."""
    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")

    questions = QuestionBankDAO.get_questions(bank_id)
    return {"questions": questions, "bank": bank}


@router.put("/{bank_id}", response_model=BankResponse)
async def update_bank(bank_id: int, request: BankUpdate):
    """Update a question bank."""
    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")

    updated_bank = QuestionBankDAO.update(bank_id, request.name, request.description)
    return updated_bank


@router.delete("/{bank_id}/questions/{question_id}")
async def remove_question(bank_id: int, question_id: int):
    """Remove a single question from a bank."""
    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")

    success = QuestionBankDAO.remove_question(bank_id, question_id)
    if not success:
        raise HTTPException(status_code=404, detail="题目不在该题库中")

    return {"message": "移除成功"}


@router.post("/{bank_id}/questions/batch-remove")
async def batch_remove_questions(bank_id: int, request: BatchRemoveRequest):
    """Batch remove questions from a bank."""
    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")

    removed = QuestionBankDAO.remove_questions(bank_id, request.question_ids)
    return {"message": f"成功移除 {removed} 道题目", "removed": removed}


@router.get("/{bank_id}/available-questions")
async def get_available_questions(
    bank_id: int,
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get questions available for import (not in the bank)."""
    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")

    questions = QuestionBankDAO.get_available_questions(
        bank_id, category, difficulty, search, limit, offset
    )
    return {"questions": questions}


@router.get("/{bank_id}/statistics", response_model=BankStatistics)
async def get_bank_statistics(bank_id: int):
    """Get statistics for a question bank."""
    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")

    stats = QuestionBankDAO.get_statistics(bank_id)
    return stats


@router.get("/{bank_id}/export")
async def export_bank(bank_id: int, format: str = Query("json", pattern="^(json|csv)$")):
    """Export a question bank as JSON or CSV."""
    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")

    questions = QuestionBankDAO.get_questions(bank_id, limit=10000)
    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"{bank['name']}_{timestamp}"

    if format == "json":
        # Export as JSON
        data = {
            "bank": {
                "id": bank["id"],
                "name": bank["name"],
                "description": bank["description"],
                "created_at": bank["created_at"],
            },
            "questions": questions,
        }
        content = json.dumps(data, ensure_ascii=False, indent=2)
        media_type = "application/json"
        filename += ".json"
    else:
        # Export as CSV
        output = io.StringIO()
        if questions:
            fieldnames = ["id", "title", "category", "difficulty", "tags", "expected_answer"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for q in questions:
                writer.writerow({k: q.get(k, "") for k in fieldnames})
        content = output.getvalue()
        media_type = "text/csv"
        filename += ".csv"

    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{bank_id}/clone", response_model=BankResponse)
async def clone_bank(bank_id: int, request: CloneBankRequest):
    """Clone a question bank with all its questions."""
    bank = QuestionBankDAO.get_by_id(bank_id)
    if not bank:
        raise HTTPException(status_code=404, detail="题库未找到")

    new_name = request.name if request.name else f"{bank['name']} - 副本"
    new_description = request.description if request.description is not None else bank["description"]

    cloned_bank = QuestionBankDAO.clone(bank_id, new_name, new_description)
    return cloned_bank


@router.post("/batch/delete")
async def batch_delete_banks(request: BankBatchDeleteRequest):
    """Batch delete question banks."""
    if not request.bank_ids:
        raise HTTPException(status_code=400, detail="未提供题库ID")

    try:
        deleted = QuestionBankDAO.batch_delete(request.bank_ids)
        return {"message": f"成功删除 {deleted} 个题库", "deleted": deleted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量删除失败: {str(e)}")


@router.post("/batch/export")
async def batch_export_banks(request: BankBatchExportRequest):
    """Batch export question banks."""
    if not request.bank_ids:
        raise HTTPException(status_code=400, detail="未提供题库ID")

    try:
        banks_data = QuestionBankDAO.get_multiple_with_details(request.bank_ids)
        timestamp = datetime.now().strftime("%Y%m%d")

        if request.format == "json":
            # Export as JSON
            content = json.dumps(banks_data, ensure_ascii=False, indent=2)
            media_type = "application/json"
            filename = f"banks_export_{timestamp}.json"
        else:
            # Export as CSV (flattened)
            output = io.StringIO()
            fieldnames = ["bank_id", "bank_name", "question_id", "question_title", "category", "difficulty", "tags"]
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()

            for bank in banks_data:
                for q in bank.get("questions", []):
                    writer.writerow({
                        "bank_id": bank["id"],
                        "bank_name": bank["name"],
                        "question_id": q.get("id", ""),
                        "question_title": q.get("title", ""),
                        "category": q.get("category", ""),
                        "difficulty": q.get("difficulty", ""),
                        "tags": q.get("tags", ""),
                    })

            content = output.getvalue()
            media_type = "text/csv"
            filename = f"banks_export_{timestamp}.csv"

        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量导出失败: {str(e)}")


@router.post("/batch/clone")
async def batch_clone_banks(request: BankBatchCloneRequest):
    """Batch clone question banks."""
    if not request.bank_ids:
        raise HTTPException(status_code=400, detail="未提供题库ID")

    try:
        cloned_banks = QuestionBankDAO.batch_clone(request.bank_ids, request.name_suffix)
        return {
            "message": f"成功克隆 {len(cloned_banks)} 个题库",
            "cloned": len(cloned_banks),
            "banks": cloned_banks,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量克隆失败: {str(e)}")
