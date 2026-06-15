"""API routes for document management."""

import os
import uuid
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from typing import Optional

from app.models.schemas import DocumentUploadResponse, DocumentResponse
from app.models.db_models import DocumentDAO
from app.services.document_parser import parse_document

router = APIRouter(prefix="/api/docs", tags=["documents"])

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload a document for processing."""
    # Validate file extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式。支持: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read file content
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过限制 (10MB)")

    # Parse content
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text_content = content.decode("gbk")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="无法解析文件编码")

    # Parse document
    file_type = ext.lstrip(".")
    parsed_content = parse_document(text_content, file_type)

    # Save to database
    doc = DocumentDAO.create(
        filename=file.filename,
        file_type=file_type,
        content=parsed_content,
    )

    return doc


@router.get("")
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List uploaded documents."""
    offset = (page - 1) * page_size
    docs = DocumentDAO.get_all(page_size, offset)
    return {"documents": docs, "page": page, "page_size": page_size}


@router.get("/{doc_id}")
async def get_document(doc_id: int):
    """Get a document by ID."""
    doc = DocumentDAO.get_by_id(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档未找到")
    return doc


@router.delete("/{doc_id}")
async def delete_document(doc_id: int):
    """Delete a document."""
    success = DocumentDAO.delete(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="文档未找到")
    return {"message": "删除成功"}
