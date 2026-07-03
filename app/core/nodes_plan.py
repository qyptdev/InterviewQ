"""Plan node for question generation."""

import json
import logging
import math

from app.config import MAX_BATCH_SIZE
from app.core.state_models import QuestionPlan
from app.llm.client import get_llm_router
from app.llm.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

# RAG retrieval configuration
RAG_TOP_K = 5  # Number of chunks to retrieve
RAG_CHUNK_SIZE = 1024
RAG_CHUNK_OVERLAP = 200


async def _retrieve_rag_context(
    resume_text: str,
    jd_text: str,
    job_title: str,
) -> str:
    """Retrieve relevant context from resume and JD using HybridRetriever.

    Indexes resume and JD chunks, then retrieves top-k relevant chunks
    based on the job title as query.

    Args:
        resume_text: Full resume text.
        jd_text: Job description text.
        job_title: Target job title used as search query.

    Returns:
        Concatenated retrieved context string, or empty string on failure.
    """
    if not resume_text and not jd_text:
        logger.info("RAG skipped: no resume or JD text provided")
        return ""

    try:
        from app.rag.chunker import chunk_text
        from app.rag.retriever import HybridRetriever

        # Build documents from resume and JD
        documents = []
        if resume_text:
            resume_chunks = chunk_text(
                resume_text,
                chunk_size=RAG_CHUNK_SIZE,
                chunk_overlap=RAG_CHUNK_OVERLAP,
            )
            for i, chunk in enumerate(resume_chunks):
                documents.append({
                    "content": chunk,
                    "id": f"resume_{i}",
                    "filename": "resume",
                })
            logger.info(f"RAG: chunked resume into {len(resume_chunks)} chunks")

        if jd_text:
            jd_chunks = chunk_text(
                jd_text,
                chunk_size=RAG_CHUNK_SIZE,
                chunk_overlap=RAG_CHUNK_OVERLAP,
            )
            for i, chunk in enumerate(jd_chunks):
                documents.append({
                    "content": chunk,
                    "id": f"jd_{i}",
                    "filename": "jd",
                })
            logger.info(f"RAG: chunked JD into {len(jd_chunks)} chunks")

        if not documents:
            logger.info("RAG skipped: no documents after chunking")
            return ""

        # Index and search with strict timeout to prevent memory blow-up
        import asyncio
        retriever = HybridRetriever(alpha=0.5)
        try:
            await asyncio.wait_for(retriever.index(documents), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("RAG indexing timed out (30s), falling back to no-RAG mode")
            return ""

        # Use job title as primary query; fallback to generic query
        query = job_title if job_title else "面试相关技能和经验"
        results = await retriever.search(query, top_k=RAG_TOP_K)

        if not results:
            logger.warning("RAG: no relevant chunks retrieved")
            return ""

        # Concatenate retrieved chunks
        context_parts = []
        for r in results:
            content = r.get("content", "").strip()
            source = r.get("filename", "unknown")
            score = r.get("combined_score", 0)
            if content:
                context_parts.append(f"[{source} (score={score:.2f})] {content}")

        rag_context = "\n\n".join(context_parts)
        logger.info(
            f"RAG: retrieved {len(results)} chunks "
            f"({len(rag_context)} chars) for query='{query}'"
        )
        return rag_context

    except Exception as e:
        logger.warning(f"RAG retrieval failed, falling back to no-RAG mode: {e}")
        return ""


async def analyze_resume(resume_text: str) -> dict:
    """Analyze resume and extract key information."""
    router = get_llm_router()

    system_prompt = load_prompt("resume_analysis.txt")

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": f"请分析以下简历：\n\n{resume_text}"
        }
    ]

    try:
        response = await router.generate_with_fallback(
            messages,
            use_light=True,
            response_format={"type": "json_object"},
        )
        return json.loads(response)
    except json.JSONDecodeError as e:
        logger.error(
            f"Resume analysis failed: Invalid JSON response from LLM. "
            f"Error: {e}, Response: {response[:200] if 'response' in locals() else 'N/A'}"
        )
        return {"skills": [], "experience_years": 0, "tech_stack": [], "highlights": []}
    except Exception as e:
        logger.error(
            f"Resume analysis failed: {type(e).__name__}: {e}",
            exc_info=True
        )
        return {"skills": [], "experience_years": 0, "tech_stack": [], "highlights": []}


async def create_question_plan(
    resume_summary: str,
    jd_requirements: str,
    question_count: int = 10,
    job_title: str = "",
    rag_context: str = "",
    custom_batch_size: int | None = None,
    concurrency: int = 1,
) -> QuestionPlan:
    """Create a plan for question generation based on resume and JD.

    Args:
        resume_summary: Summary of the candidate's resume.
        jd_requirements: Job description requirements text.
        question_count: Number of questions to generate.
        job_title: Target job title for question generation.
        rag_context: Retrieved RAG context chunks (optional).
        custom_batch_size: Optional user-specified batch size. When provided,
            overrides the LLM-suggested batch_size so that the plan's
            total_batches matches the actual per-batch generation count.
        concurrency: Max concurrent batch generation (written into the plan).

    Returns:
        QuestionPlan with generation parameters.
    """
    router = get_llm_router()

    system_prompt = load_prompt("plan_creation.txt")

    # Build user message with optional RAG context
    rag_section = ""
    if rag_context:
        rag_section = f"\n\n=== RAG 检索到的相关片段 ===\n{rag_context}\n=== END RAG ===\n"

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": f"""目标岗位：{job_title or '未指定'}

岗位要求：{jd_requirements or '无'}

候选人简历：
{resume_summary or '无'}
{rag_section}
需要生成 {question_count} 道面试题，请制定出题计划。"""
        }
    ]

    try:
        response = await router.generate_with_fallback(
            messages,
            use_light=True,
            response_format={"type": "json_object"},
        )
        data = json.loads(response)

        # Normalize question_types: LLM may return list[dict] with {"name": ..., "count": ...}
        # instead of list[str].  Extract the "name" field from dicts if so.
        raw_question_types = data.get("question_types", ["项目深挖"])
        if isinstance(raw_question_types, list):
            normalized_types = []
            for item in raw_question_types:
                if isinstance(item, dict):
                    # Take "name" or "type" key; fall back to str(item)
                    name = item.get("name") or item.get("type") or str(item)
                    if isinstance(name, str) and name.strip():
                        normalized_types.append(name.strip())
                elif isinstance(item, str) and item.strip():
                    normalized_types.append(item.strip())
            question_types = normalized_types if normalized_types else ["项目深挖"]
        else:
            question_types = ["项目深挖"]

        # Use LLM-suggested batch_size but cap it, then calculate total_batches
        # to ensure we cover the requested question_count
        if custom_batch_size and custom_batch_size > 0:
            batch_size = custom_batch_size
        else:
            llm_batch_size = data.get("batch_size", 5)
            batch_size = max(1, min(llm_batch_size, MAX_BATCH_SIZE))  # Cap via central constant
        total_batches = math.ceil(question_count / batch_size)

        return QuestionPlan(
            job_title=job_title,
            resume_summary=resume_summary,
            jd_requirements=jd_requirements,
            rag_context=rag_context,
            question_types=question_types,
            difficulty_distribution=data.get("difficulty_distribution", {"easy": 2, "medium": 3, "hard": 1}),
            total_batches=total_batches,
            batch_size=batch_size,
            concurrency=concurrency,
        )
    except Exception as e:
        logger.error(f"Question plan creation failed: {e}")
        return QuestionPlan(
            job_title=job_title,
            resume_summary=resume_summary,
            jd_requirements=jd_requirements,
            rag_context=rag_context,
            concurrency=concurrency,
        )
