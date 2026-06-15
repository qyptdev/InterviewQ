"""Tests for prompt template loader: loading, variable substitution, caching.

Covers:
- load_prompt with valid templates and variable substitution
- Missing template file raises FileNotFoundError
- Missing variable raises ValueError
- Caching behavior (lru_cache)
- clear_cache resets the cache
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.llm.prompt_loader import load_prompt, clear_cache, PROMPTS_DIR, _load_template_cached


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear template cache before and after each test."""
    clear_cache()
    yield
    clear_cache()


class TestLoadPrompt:
    """Tests for prompt template loading and rendering."""

    def test_load_existing_template(self):
        """Loading an existing template returns its content."""
        # interview_user.txt has no variables, safe to load directly
        result = load_prompt("interview_user.txt")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_variable_substitution(self):
        """Template variables are correctly substituted."""
        result = load_prompt(
            "generate_questions.txt",
            category="技术",
            difficulty="medium",
            topic="Python",
            language="zh",
        )
        assert isinstance(result, str)
        assert len(result) > 0
        # The rendered prompt should not contain raw {variable} placeholders
        # (unless the template intentionally includes them)
        assert "{category}" not in result
        assert "{difficulty}" not in result

    def test_missing_template_raises_file_not_found(self):
        """Loading a non-existent template raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Prompt template not found"):
            load_prompt("nonexistent_template_xyz.txt")

    def test_missing_variable_raises_value_error(self):
        """Missing required variable raises ValueError."""
        # generate_questions.txt requires category, difficulty, topic, language
        with pytest.raises(ValueError, match="Missing template variable"):
            load_prompt("generate_questions.txt", category="tech")
            # Missing: difficulty, topic, language

    def test_followup_question_template(self):
        """Follow-up question template loads with all variables."""
        result = load_prompt(
            "followup_question.txt",
            job_role="Backend Developer",
            question_text="Explain Python GIL",
            user_answer="I don't know",
            feedback_summary="The candidate showed no understanding.",
            score=20.0,
        )
        assert isinstance(result, str)
        assert "Backend Developer" in result or len(result) > 0

    def test_interview_system_template(self):
        """Interview system template loads with all variables."""
        result = load_prompt(
            "interview_system.txt",
            job_role="Frontend Engineer",
            question_index=1,
            question_text="What is React?",
            user_answer="A JavaScript library",
        )
        assert isinstance(result, str)
        assert len(result) > 0


class TestCaching:
    """Tests for template caching behavior."""

    def test_cache_hit_on_second_load(self):
        """Second load of same template uses cache (no disk read)."""
        # First load populates cache
        load_prompt("interview_user.txt")

        # Check cache info
        info = _load_template_cached.cache_info()
        assert info.misses >= 1

        # Second load should be a cache hit
        load_prompt("interview_user.txt")
        info_after = _load_template_cached.cache_info()
        assert info_after.hits >= 1

    def test_clear_cache_resets(self):
        """clear_cache resets the LRU cache."""
        load_prompt("interview_user.txt")
        info_before = _load_template_cached.cache_info()
        assert info_before.currsize > 0

        clear_cache()
        info_after = _load_template_cached.cache_info()
        assert info_after.currsize == 0

    def test_different_templates_cached_separately(self):
        """Different templates are cached as separate entries."""
        load_prompt("interview_user.txt")
        load_prompt("interview_feedback_stream.txt",
                     job_role="Dev",
                     question_index=1,
                     question_text="Q",
                     user_answer="A")

        info = _load_template_cached.cache_info()
        assert info.currsize >= 2


class TestPromptsDirectory:
    """Tests for prompts directory configuration."""

    def test_prompts_dir_exists(self):
        """PROMPTS_DIR points to an existing directory."""
        assert PROMPTS_DIR.exists()
        assert PROMPTS_DIR.is_dir()

    def test_known_templates_exist(self):
        """All expected template files exist in the prompts directory."""
        expected_templates = [
            "generate_questions.txt",
            "interview_system.txt",
            "interview_user.txt",
            "followup_question.txt",
            "interview_feedback_stream.txt",
            "resume_analysis.txt",
        ]
        for template_name in expected_templates:
            template_path = PROMPTS_DIR / template_name
            assert template_path.exists(), f"Missing template: {template_name}"
