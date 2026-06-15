"""Text chunker for RAG pipeline."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def chunk_text(
    text: str,
    chunk_size: int = 1024,
    chunk_overlap: int = 200,
    separators: Optional[list[str]] = None,
) -> list[str]:
    """Split text into chunks with overlap.

    Args:
        text: Input text to chunk
        chunk_size: Maximum chunk size in characters
        chunk_overlap: Overlap between chunks
        separators: List of separators to try (default: newlines, periods, spaces)

    Returns:
        List of text chunks
    """
    if not text:
        return []

    if separators is None:
        separators = ["\n\n", "\n", "。", ".", " ", ""]

    chunks = []
    current_chunk = ""

    # Split by paragraphs first
    paragraphs = text.split("\n\n")

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding this paragraph exceeds chunk size
        if len(current_chunk) + len(para) > chunk_size:
            # Save current chunk if not empty
            if current_chunk:
                chunks.append(current_chunk.strip())

            # Start new chunk with overlap from previous
            if chunk_overlap > 0 and current_chunk:
                # Get last chunk_overlap characters
                overlap_text = current_chunk[-chunk_overlap:]
                current_chunk = overlap_text + "\n\n" + para
            else:
                current_chunk = para

            # If single paragraph is too long, split it further
            while len(current_chunk) > chunk_size:
                # Try to split by sentences
                split_point = _find_split_point(current_chunk, chunk_size, separators)
                if split_point > 0:
                    chunks.append(current_chunk[:split_point].strip())
                    current_chunk = current_chunk[split_point - chunk_overlap:]
                else:
                    # Force split at chunk_size
                    chunks.append(current_chunk[:chunk_size].strip())
                    current_chunk = current_chunk[chunk_size - chunk_overlap:]
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    # Add last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _find_split_point(text: str, max_size: int, separators: list[str]) -> int:
    """Find the best split point in text."""
    for sep in separators:
        if not sep:
            # Split at max_size
            return max_size

        # Look for separator near max_size
        pos = text.rfind(sep, 0, max_size)
        if pos > 0:
            return pos + len(sep)

    return max_size


def chunk_documents(
    documents: list[dict],
    chunk_size: int = 1024,
    chunk_overlap: int = 200,
) -> list[dict]:
    """Chunk multiple documents.

    Args:
        documents: List of documents with 'content' field
        chunk_size: Maximum chunk size
        chunk_overlap: Overlap between chunks

    Returns:
        List of chunks with metadata
    """
    all_chunks = []

    for doc in documents:
        content = doc.get("content", "")
        doc_id = doc.get("id", "")
        filename = doc.get("filename", "")

        chunks = chunk_text(content, chunk_size, chunk_overlap)

        for i, chunk in enumerate(chunks):
            all_chunks.append({
                "content": chunk,
                "metadata": {
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                },
            })

    return all_chunks
