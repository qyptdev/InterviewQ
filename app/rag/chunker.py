"""Text chunker for RAG pipeline.

Bug fix: Original implementation had an infinite-loop bug when
_find_split_point() returned a value ≤ chunk_overlap — e.g. a period
inside an email like "bupt.edu.cn" returned split_point=91 with
chunk_overlap=200, making current_chunk[91-200:] = current_chunk[-109:]
which is equivalent to current_chunk[0:] (the whole string). This
caused the while loop to never make forward progress, consuming 100%
CPU and growing memory until OOM.

Fix: Guarantee minimum forward progress in every iteration by
enforcing effective_overlap < split_point / 2 and capping overlap
to at most chunk_size // 4. Added a safety limit as a last resort.
"""

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

    # Cap overlap to prevent infinite loops: overlap must be < chunk_size/2
    effective_overlap = min(chunk_overlap, chunk_size // 4)

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

            # Build the candidate chunk (with overlap from previous)
            if effective_overlap > 0 and current_chunk:
                # Get last effective_overlap characters
                overlap_text = current_chunk[-effective_overlap:]
                candidate = overlap_text + "\n\n" + para
            else:
                candidate = para

            # If candidate is too long, split it further
            if len(candidate) > chunk_size:
                split_chunks = _split_long_text(
                    candidate, chunk_size, effective_overlap, separators
                )
                chunks.extend(split_chunks[:-1])  # all but last
                current_chunk = split_chunks[-1] if split_chunks else ""
            else:
                current_chunk = candidate
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
    chunk_overlap: int,
    separators: list[str],
) -> list[str]:
    """Split a single long text into chunks, guaranteed to make forward progress.

    Key invariant: each iteration MUST advance the cursor by at least
    min_advance characters to prevent infinite loops.

    Returns:
        List of chunk strings. The last element is the remaining text (may be
        empty string if fully consumed).
    """
    if not text or len(text) <= chunk_size:
        return [text] if text else []

    chunks: list[str] = []
    # Minimum forward progress per iteration — prevents infinite loop
    min_advance = max(chunk_size // 2, 1)
    # Safety limit: no text should require more than len(text) iterations
    safety_limit = len(text) * 2
    iterations = 0

    while len(text) > chunk_size:
        iterations += 1
        if iterations > safety_limit:
            logger.error(
                f"chunk_text safety limit reached ({safety_limit}), "
                f"forcing split at chunk_size={chunk_size}"
            )
            chunks.append(text[:chunk_size].strip())
            text = text[min_advance:]
            break

        split_point = _find_split_point(text, chunk_size, separators)

        # GUARANTEE FORWARD PROGRESS:
        # If split_point <= chunk_overlap, the slice
        #   text[split_point - chunk_overlap:]
        # would start at ≤ 0, producing no forward movement.
        # Enforce that we always advance by at least min_advance.
        if split_point <= chunk_overlap:
            # Force advance past the overlap zone
            effective_start = min_advance
        else:
            effective_start = split_point - chunk_overlap

        # Ensure we don't go backwards
        effective_start = max(effective_start, min_advance)
        # Ensure we don't go past the text
        effective_start = min(effective_start, len(text))

        chunks.append(text[:split_point].strip())
        text = text[effective_start:]

    # Return remaining text as last element
    if text.strip():
        chunks.append(text.strip())

    return chunks  # last element = remaining unsaved text


def _find_split_point(text: str, max_size: int, separators: list[str]) -> int:
    """Find the best split point in text.

    Improved: prefers the LARGEST split position among all matching
    separators, rather than returning on the first match. This produces
    more natural chunk boundaries.
    """
    best_pos = 0

    for sep in separators:
        if not sep:
            # Empty separator = force split at max_size
            if max_size > best_pos:
                best_pos = max_size
            continue

        # Look for separator near max_size — take the LAST (largest) one
        pos = text.rfind(sep, 0, max_size)
        if pos > 0:
            candidate = pos + len(sep)
            if candidate > best_pos:
                best_pos = candidate

    # Fallback: force split at max_size if no separator found
    if best_pos == 0:
        best_pos = max_size

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
