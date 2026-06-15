"""Prompt template loader with caching.

Loads prompt templates from the prompts/ directory and supports
variable substitution via str.format(). Templates are cached after
first load to avoid repeated disk reads.
"""

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Base directory for prompt templates
PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


@lru_cache(maxsize=32)
def _load_template_cached(template_name: str) -> str:
    """Load a template file from disk (cached).

    Args:
        template_name: Name of the template file (e.g., 'resume_analysis.txt').

    Returns:
        Template content as string.

    Raises:
        FileNotFoundError: If template file does not exist.
    """
    template_path = PROMPTS_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(
            f"Prompt template not found: {template_path}. "
            f"Available templates: {list(PROMPTS_DIR.glob('*.txt'))}"
        )
    content = template_path.read_text(encoding="utf-8")
    logger.debug("Loaded prompt template: %s", template_name)
    return content


def load_prompt(template_name: str, **kwargs) -> str:
    """Load a prompt template and substitute variables.

    Args:
        template_name: Name of the template file (e.g., 'resume_analysis.txt').
        **kwargs: Variables to substitute in the template.

    Returns:
        Rendered prompt string with variables substituted.

    Example:
        >>> prompt = load_prompt("resume_analysis.txt", resume_text="...")
    """
    template = _load_template_cached(template_name)
    try:
        return template.format(**kwargs)
    except KeyError as e:
        logger.error(
            "Missing template variable %s in %s. Provided: %s",
            e, template_name, list(kwargs.keys()),
        )
        raise ValueError(
            f"Missing template variable {e} for {template_name}. "
            f"Required variables not provided."
        ) from e


def clear_cache() -> None:
    """Clear the template cache. Useful for testing."""
    _load_template_cached.cache_clear()
