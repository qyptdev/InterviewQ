"""Application configuration using Pydantic BaseSettings."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_secret_key: str = ""

    # Logging
    log_level: str = "INFO"
    log_format: str = "default"

    # Database
    database_url: str = "sqlite:///./data/interview.db"

    # LLM - Primary model (complex tasks)
    llm_primary_base_url: str = ""
    llm_primary_api_key: str = ""
    llm_primary_model: str = ""

    # LLM - Light model (simple tasks)
    llm_light_base_url: str = ""
    llm_light_api_key: str = ""
    llm_light_model: str = ""

    # LLM - Embedding model
    llm_embedding_base_url: str = ""
    llm_embedding_api_key: str = ""
    llm_embedding_model: str = ""

    # Feature toggles (default False to prevent OOM on low-memory systems)
    embedding_enabled: bool = False
    rag_enabled: bool = False

    # LLM Parameters
    llm_temperature: float = 0.7
    llm_max_tokens: int = 2048

    # LLM Timeouts (split by phase)
    llm_connect_timeout: float = 10.0
    llm_read_timeout: float = 300.0
    llm_write_timeout: float = 30.0
    llm_pool_timeout: float = 60.0

    # Rate Limiting
    rate_limit_enabled: bool = False
    rate_limit_per_minute: int = 30

    # Question Generation - Debug Logging
    enable_generation_debug_log: bool = True

    # Memory & streaming safety limits
    max_stream_collect_chars: int = 500_000

    # SSE heartbeat interval (seconds) — prevents proxy/browser timeout
    sse_heartbeat_interval: float = 15.0

    # Max past events per job (prevents unbounded memory growth)
    job_max_past_events: int = 200

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


# =============================================================================
# Question Generation — Centralized Constants (SSOT)
# All generation parameters are defined here. Other modules MUST import
# from this file rather than redefining locally.
# =============================================================================

# --- Question count limits ---
MAX_QUESTION_COUNT: int = 100
"""Maximum number of questions allowed per generation request."""

# --- Batch & concurrency limits ---
MAX_BATCH_SIZE: int = 15
"""Maximum questions per single LLM call to avoid response truncation."""

MAX_LLM_UNDERPRODUCE_RETRIES: int = 3
"""Max retries when LLM returns fewer questions than requested in a batch."""

# --- Gap-fill (supplement) strategy ---
OVER_REQUEST_FACTOR: float = 1.3
"""Multiplier applied to needed count when requesting supplement questions,
accounting for expected dedup losses."""

MAX_SUPPLEMENT_ROUNDS: int = 10
"""Maximum gap-fill supplement rounds after the initial two passes."""

MAX_GENERATION_MULTIPLIER: int = 5
"""Safety limit: max total LLM calls = question_count * this multiplier.
Prevents infinite loops if LLM consistently under-produces."""

# --- Resume/JD question ratio ---
RESUME_QUESTION_RATIO: float = 0.7
"""Default ratio of resume-specific questions (70%) when a full resume is
provided. Remaining fraction goes to JD/general supplement."""

# Dynamic ratio mapping: key = input completeness level
RESUME_QUESTION_RATIOS: dict[str, float] = {
    "full_resume": 0.7,   # Resume has substantive content
    "partial_resume": 0.3, # Resume is minimal / incomplete
    "job_only": 0.0,       # No resume at all, only JD/job_title
}
"""Dynamic ratio of resume questions based on input completeness.
full_resume: 70% resume-specific, 30% supplement
partial_resume: 30% resume-specific, 70% supplement
job_only: 0% resume-specific, 100% supplement"""

# --- File limits ---
MAX_RESUME_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB

# --- Memory & streaming safety ---
MAX_STREAM_COLLECT_CHARS: int = 500_000
MAX_RESUME_ANALYSIS_CHARS: int = 30_000
MAX_RESUME_SUMMARY_CHARS: int = 20_000
MAX_RAG_CONTEXT_RESUME_CHARS: int = 10_000
MAX_RAG_CONTEXT_JD_CHARS: int = 5_000


# Generation mode configurations
GENERATION_MODES = {
    "fast": {
        "display_name": "快速模式",
        "description": "快速预览，基础质量",
        "temperature": 0.8,
        "max_validation_retries": 1,
        "validation_strict": False,
        "estimated_time": "30-60 秒",
        "icon": "⚡",
        "recommended_concurrency": 3,
        "recommended_batch_size": 8,
    },
    "standard": {
        "display_name": "标准模式",
        "description": "平衡速度与质量（推荐）",
        "temperature": 0.7,
        "max_validation_retries": 2,
        "validation_strict": True,
        "estimated_time": "60-120 秒",
        "icon": "⚙️",
        "recommended_concurrency": 2,
        "recommended_batch_size": 5,
    },
    "deep": {
        "display_name": "深度模式",
        "description": "高质量输出，严格验证",
        "temperature": 0.5,
        "max_validation_retries": 3,
        "validation_strict": True,
        "dedup_strict": True,
        "estimated_time": "120-180 秒",
        "icon": "🎯",
        "recommended_concurrency": 1,
        "recommended_batch_size": 5,
    },
}


def get_generation_mode_config(mode: str = "standard") -> dict:
    """Get generation mode configuration.

    Args:
        mode: Generation mode ('fast', 'standard', 'deep').

    Returns:
        Mode configuration dict.
    """
    return GENERATION_MODES.get(mode, GENERATION_MODES["standard"])

