"""Scoring service for answer evaluation."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def calculate_score(score: float) -> float:
    """Normalize score to 0-100 range."""
    return max(0.0, min(100.0, score))


def get_score_label(score: float) -> str:
    """Get a label for the score."""
    if score >= 90:
        return "优秀"
    elif score >= 80:
        return "良好"
    elif score >= 70:
        return "中等"
    elif score >= 60:
        return "及格"
    else:
        return "需要改进"


def calculate_session_score(scores: list[float]) -> dict:
    """Calculate overall session score statistics."""
    if not scores:
        return {"average": 0, "min": 0, "max": 0, "label": "无数据"}

    avg = sum(scores) / len(scores)
    return {
        "average": round(avg, 2),
        "min": min(scores),
        "max": max(scores),
        "label": get_score_label(avg),
    }
