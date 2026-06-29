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

    Uses a two-phase approach:
    1. Split by double-newlines into paragraphs
    2. For each paragraph that exceeds chunk_size, split by sentence boundaries

    Args:
        text: Input text to chunk
        chunk_size: Maximum chunk size in characters
        chunk_overlap: Overlap between chunks (capped at chunk_size // 4)
        separators: List of separators to try (default: newlines, periods, spaces)

    Returns:
        List of text chunks
    """
    if not text:
        return []

    # Cap overlap to prevent pathological splitting (overlap >= effective advance)
    effective_overlap = min(chunk_overlap, chunk_size // 4)

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
            if effective_overlap > 0 and current_chunk:
                overlap_text = current_chunk[-effective_overlap:]
                current_chunk = overlap_text + "\n\n" + para
            else:
                current_chunk = para

            # If single paragraph is too long, split it further
            current_chunk = _split_long_text(current_chunk, chunk_size, effective_overlap, separators, chunks)
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    # Add last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _split_long_text(
    text: str,
    chunk_size: int,
    overlap: int,
    separators: list[str],
    chunks: list[str],
) -> str:
    """Split a long text into chunks, appending results to chunks list.

    Returns the remaining un-consumed tail of the text.
    """
    # Minimum advance per iteration to prevent O(n²) or infinite loop
    min_advance = max(chunk_size // 2, 1)

    safety_limit = len(text) * 2  # absolute upper bound on iterations
    iterations = 0

    while len(text) > chunk_size and iterations < safety_limit:
        iterations += 1
        split_point = _find_split_point(text, chunk_size, separators)

        # Ensure we always advance at least min_advance characters
        if split_point < min_advance:
            split_point = min_advance

        chunks.append(text[:split_point].strip())
        next_start = max(split_point - overlap, 0)
        # Guarantee forward progress
        if next_start >= split_point:
            next_start = split_point
        text = text[next_start:]

    return text


def _find_split_point(text: str, max_size: int, separators: list[str]) -> int:
    """Find the best split point in text.

    Tries separators in order, preferring the one closest to max_size.
    Falls back to splitting at max_size if no separator found.
    """
    best_pos = 0
    for sep in separators:
        if not sep:
            # Empty separator = split at max_size
            return max_size

        # Look for separator near max_size (search backwards from max_size)
        pos = text.rfind(sep, 0, max_size)
        if pos > best_pos:
            best_pos = pos + len(sep)

    # If no good separator found, force split at max_size
    if best_pos == 0:
        return max_size
    return best_pos


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
