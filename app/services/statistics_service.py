"""Statistics service for interview session analytics."""

import logging
from typing import Optional
from app.models.db_models import SessionDAO, InterviewQuestionDAO

logger = logging.getLogger(__name__)


class StatisticsService:
    """Service for generating detailed session statistics and analytics."""

    @staticmethod
    def get_session_statistics(session_id: int) -> dict:
        """Get detailed statistics for a session.

        Returns:
            Dictionary with comprehensive session statistics including:
            - Basic counts (total, answered, skipped, unanswered)
            - Score metrics (average, min, max, distribution)
            - Time metrics (total time, average time per question)
            - Category breakdown
            - Progress percentage
        """
        session = SessionDAO.get_by_id(session_id)
        if not session:
            raise ValueError("Session not found")

        questions = InterviewQuestionDAO.get_by_session(session_id)

        # Basic counts
        total_questions = len(questions)
        answered_questions = [q for q in questions if q["user_answer"] and q["score"] != -1]
        skipped_questions = [q for q in questions if q["score"] == -1]
        unanswered_questions = [q for q in questions if not q["user_answer"]]
        bookmarked_questions = [q for q in questions if q.get("is_bookmarked", 0)]

        # Score metrics
        scores = [q["score"] for q in answered_questions if q["score"] is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
        min_score = min(scores) if scores else 0
        max_score = max(scores) if scores else 0

        # Score distribution
        score_ranges = {"0-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
        for score in scores:
            if score < 40:
                score_ranges["0-40"] += 1
            elif score < 60:
                score_ranges["40-60"] += 1
            elif score < 80:
                score_ranges["60-80"] += 1
            else:
                score_ranges["80-100"] += 1

        # Time metrics
        total_time = sum([q.get("time_spent", 0) for q in questions])
        answered_times = [q.get("time_spent", 0) for q in answered_questions if q.get("time_spent", 0) > 0]
        avg_time_per_question = sum(answered_times) / len(answered_times) if answered_times else 0

        # Progress percentage
        progress = (len(answered_questions) + len(skipped_questions)) / total_questions * 100 if total_questions > 0 else 0

        return {
            "session_id": session_id,
            "session_title": session["title"],
            "session_status": session["status"],
            "counts": {
                "total": total_questions,
                "answered": len(answered_questions),
                "skipped": len(skipped_questions),
                "unanswered": len(unanswered_questions),
                "bookmarked": len(bookmarked_questions),
            },
            "scores": {
                "average": round(avg_score, 2),
                "min": min_score,
                "max": max_score,
                "distribution": score_ranges,
            },
            "time": {
                "total_seconds": total_time,
                "average_per_question": round(avg_time_per_question, 2),
                "total_formatted": StatisticsService._format_time(total_time),
            },
            "progress": {
                "percentage": round(progress, 2),
                "completed": len(answered_questions) + len(skipped_questions),
                "remaining": len(unanswered_questions),
            },
        }

    @staticmethod
    def get_time_analysis(session_id: int) -> dict:
        """Get detailed time analysis for questions in a session.

        Returns:
            Dictionary with per-question time breakdown and insights.
        """
        questions = InterviewQuestionDAO.get_by_session(session_id)
        answered = [q for q in questions if q["user_answer"] and q["score"] != -1]

        time_data = []
        for q in answered:
            time_spent = q.get("time_spent", 0)
            time_data.append({
                "question_id": q["id"],
                "question_text": q["question_text"][:100] + "..." if len(q["question_text"]) > 100 else q["question_text"],
                "time_spent": time_spent,
                "time_formatted": StatisticsService._format_time(time_spent),
                "score": q["score"],
            })

        # Sort by time spent (descending)
        time_data.sort(key=lambda x: x["time_spent"], reverse=True)

        # Calculate quartiles
        times = [q.get("time_spent", 0) for q in answered if q.get("time_spent", 0) > 0]
        times.sort()

        quartiles = {}
        if times:
            n = len(times)
            quartiles = {
                "q1": times[n // 4] if n >= 4 else times[0],
                "median": times[n // 2],
                "q3": times[3 * n // 4] if n >= 4 else times[-1],
            }

        return {
            "session_id": session_id,
            "questions": time_data,
            "quartiles": quartiles,
            "fastest": time_data[-1] if time_data else None,
            "slowest": time_data[0] if time_data else None,
        }

    @staticmethod
    def get_score_distribution(session_id: int) -> dict:
        """Get detailed score distribution analysis.

        Returns:
            Dictionary with score distribution by various dimensions.
        """
        questions = InterviewQuestionDAO.get_by_session(session_id)
        answered = [q for q in questions if q["user_answer"] and q["score"] is not None and q["score"] != -1]

        scores = [q["score"] for q in answered]

        # Basic distribution
        distribution = {
            "excellent": len([s for s in scores if s >= 80]),
            "good": len([s for s in scores if 60 <= s < 80]),
            "fair": len([s for s in scores if 40 <= s < 60]),
            "poor": len([s for s in scores if s < 40]),
        }

        # Score histogram (10-point buckets)
        histogram = {}
        for i in range(0, 101, 10):
            bucket = f"{i}-{i+9 if i < 100 else 100}"
            histogram[bucket] = len([s for s in scores if i <= s < (i + 10 if i < 100 else 101)])

        return {
            "session_id": session_id,
            "distribution": distribution,
            "histogram": histogram,
            "total_scored": len(answered),
        }

    @staticmethod
    def get_category_performance(session_id: int) -> dict:
        """Get performance analysis by question type/category.

        Returns:
            Dictionary with performance metrics grouped by category.
        """
        questions = InterviewQuestionDAO.get_by_session(session_id)
        answered = [q for q in questions if q["user_answer"] and q["score"] is not None and q["score"] != -1]

        # Group by is_followup
        regular_questions = [q for q in answered if not q.get("is_followup", 0)]
        followup_questions = [q for q in answered if q.get("is_followup", 0)]

        def calculate_metrics(questions_list):
            if not questions_list:
                return {"count": 0, "avg_score": 0, "avg_time": 0}

            scores = [q["score"] for q in questions_list if q["score"] is not None]
            times = [q.get("time_spent", 0) for q in questions_list]

            return {
                "count": len(questions_list),
                "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
                "avg_time": round(sum(times) / len(times), 2) if times else 0,
            }

        return {
            "session_id": session_id,
            "regular": calculate_metrics(regular_questions),
            "followup": calculate_metrics(followup_questions),
        }

    @staticmethod
    def get_trend_data(session_ids: list[int]) -> dict:
        """Get trend data across multiple sessions.

        Args:
            session_ids: List of session IDs to analyze.

        Returns:
            Dictionary with trend data showing performance over time.
        """
        if not session_ids:
            return {"sessions": [], "overall_trend": None}

        trend_data = []
        for sid in session_ids:
            session = SessionDAO.get_by_id(sid)
            if not session:
                continue

            questions = InterviewQuestionDAO.get_by_session(sid)
            answered = [q for q in questions if q["user_answer"] and q["score"] is not None and q["score"] != -1]
            scores = [q["score"] for q in answered if q["score"] is not None]

            trend_data.append({
                "session_id": sid,
                "session_title": session["title"],
                "created_at": session["created_at"],
                "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
                "total_questions": len(questions),
                "answered": len(answered),
            })

        # Sort by created_at
        trend_data.sort(key=lambda x: x["created_at"])

        # Calculate overall trend (simple linear regression)
        overall_trend = None
        if len(trend_data) >= 2:
            scores = [d["avg_score"] for d in trend_data]
            n = len(scores)
            x_mean = (n - 1) / 2  # indices 0, 1, 2, ... n-1
            y_mean = sum(scores) / n

            numerator = sum((i - x_mean) * (scores[i] - y_mean) for i in range(n))
            denominator = sum((i - x_mean) ** 2 for i in range(n))

            slope = numerator / denominator if denominator != 0 else 0
            overall_trend = "improving" if slope > 0.5 else "declining" if slope < -0.5 else "stable"

        return {
            "sessions": trend_data,
            "overall_trend": overall_trend,
            "total_sessions": len(trend_data),
        }

    @staticmethod
    def _format_time(seconds: int) -> str:
        """Format seconds into human-readable time string.

        Args:
            seconds: Time in seconds.

        Returns:
            Formatted string like "1h 23m 45s" or "5m 30s" or "45s".
        """
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}m {secs}s"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            return f"{hours}h {minutes}m {secs}s"
