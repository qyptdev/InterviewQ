"""Data Access Objects for database operations."""

import logging
import sqlite3
from typing import Optional
from app.database import get_db

logger = logging.getLogger(__name__)


class QuestionDAO:
    """DAO for questions table."""

    @staticmethod
    def create(title: str, category: str, difficulty: str, tags: str, expected_answer: str) -> dict:
        """Create a new question."""
        conn = get_db()
        cursor = conn.execute(
            """INSERT INTO questions (title, category, difficulty, tags, expected_answer)
               VALUES (?, ?, ?, ?, ?)""",
            (title, category, difficulty, tags, expected_answer),
        )
        conn.commit()
        return QuestionDAO.get_by_id(cursor.lastrowid)

    @staticmethod
    def get_by_id(question_id: int) -> Optional[dict]:
        """Get a question by ID."""
        conn = get_db()
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_all(
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Get all questions with optional filters."""
        conn = get_db()
        query = "SELECT * FROM questions WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)
        if difficulty:
            query += " AND difficulty = ?"
            params.append(difficulty)
        if search:
            query += " AND (title LIKE ? OR tags LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def count(category: Optional[str] = None, difficulty: Optional[str] = None, search: Optional[str] = None) -> int:
        """Count questions with optional filters."""
        conn = get_db()
        query = "SELECT COUNT(*) FROM questions WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)
        if difficulty:
            query += " AND difficulty = ?"
            params.append(difficulty)
        if search:
            query += " AND (title LIKE ? OR tags LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        return conn.execute(query, params).fetchone()[0]

    @staticmethod
    def update(question_id: int, **kwargs) -> Optional[dict]:
        """Update a question."""
        conn = get_db()
        allowed_fields = {"title", "category", "difficulty", "tags", "expected_answer"}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}

        if not updates:
            return QuestionDAO.get_by_id(question_id)

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [question_id]

        conn.execute(f"UPDATE questions SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return QuestionDAO.get_by_id(question_id)

    @staticmethod
    def delete(question_id: int) -> bool:
        """Delete a question."""
        conn = get_db()
        cursor = conn.execute("DELETE FROM questions WHERE id = ?", (question_id,))
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def batch_delete(question_ids: list[int]) -> int:
        """Batch delete questions. Returns count of deleted questions."""
        if not question_ids:
            return 0

        conn = get_db()
        placeholders = ",".join("?" * len(question_ids))
        cursor = conn.execute(
            f"DELETE FROM questions WHERE id IN ({placeholders})",
            question_ids,
        )
        conn.commit()
        deleted = cursor.rowcount
        logger.info(f"Batch deleted {deleted} questions")
        return deleted

    @staticmethod
    def batch_update(
        question_ids: list[int],
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        tags_to_add: Optional[list[str]] = None,
        tags_to_remove: Optional[list[str]] = None,
    ) -> int:
        """Batch update questions. Returns count of updated questions."""
        if not question_ids:
            return 0

        conn = get_db()
        updated = 0

        for qid in question_ids:
            question = QuestionDAO.get_by_id(qid)
            if not question:
                continue

            updates = {}

            # Update category
            if category is not None:
                updates["category"] = category

            # Update difficulty
            if difficulty is not None:
                updates["difficulty"] = difficulty

            # Update tags
            if tags_to_add or tags_to_remove:
                current_tags = set(question["tags"].split(",")) if question["tags"] else set()
                current_tags = {t.strip() for t in current_tags if t.strip()}

                if tags_to_add:
                    current_tags.update(tags_to_add)
                if tags_to_remove:
                    current_tags.difference_update(tags_to_remove)

                updates["tags"] = ",".join(sorted(current_tags))

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values()) + [qid]
                conn.execute(f"UPDATE questions SET {set_clause} WHERE id = ?", values)
                updated += 1

        conn.commit()
        logger.info(f"Batch updated {updated} questions")
        return updated

    @staticmethod
    def get_multiple(question_ids: list[int]) -> list[dict]:
        """Get multiple questions by IDs."""
        if not question_ids:
            return []

        conn = get_db()
        placeholders = ",".join("?" * len(question_ids))
        rows = conn.execute(
            f"SELECT * FROM questions WHERE id IN ({placeholders})",
            question_ids,
        ).fetchall()
        return [dict(row) for row in rows]


class SessionDAO:
    """DAO for interview_sessions table."""

    @staticmethod
    def create(title: str, job_role: str = "") -> dict:
        """Create a new interview session."""
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO interview_sessions (title, job_role) VALUES (?, ?)",
            (title, job_role),
        )
        conn.commit()
        return SessionDAO.get_by_id(cursor.lastrowid)

    @staticmethod
    def get_by_id(session_id: int) -> Optional[dict]:
        """Get a session by ID."""
        conn = get_db()
        row = conn.execute("SELECT * FROM interview_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None

        session = dict(row)
        # Add total_questions count
        count_row = conn.execute(
            "SELECT COUNT(*) FROM interview_questions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        session["total_questions"] = count_row[0] if count_row else 0
        return session

    @staticmethod
    def get_all(status: Optional[str] = None, limit: int = 50, offset: int = 0) -> list[dict]:
        """Get all sessions with optional status filter."""
        conn = get_db()
        query = "SELECT * FROM interview_sessions WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def update_status(session_id: int, status: str) -> Optional[dict]:
        """Update session status."""
        conn = get_db()
        if status == "completed":
            conn.execute(
                "UPDATE interview_sessions SET status = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, session_id),
            )
        else:
            conn.execute(
                "UPDATE interview_sessions SET status = ? WHERE id = ?",
                (status, session_id),
            )
        conn.commit()
        return SessionDAO.get_by_id(session_id)

    @staticmethod
    def pause_session(session_id: int) -> Optional[dict]:
        """Pause an interview session."""
        conn = get_db()
        conn.execute(
            "UPDATE interview_sessions SET status = 'paused', paused_at = CURRENT_TIMESTAMP WHERE id = ?",
            (session_id,),
        )
        conn.commit()
        return SessionDAO.get_by_id(session_id)

    @staticmethod
    def resume_session(session_id: int) -> Optional[dict]:
        """Resume a paused interview session."""
        conn = get_db()
        conn.execute(
            "UPDATE interview_sessions SET status = 'in_progress', paused_at = NULL WHERE id = ?",
            (session_id,),
        )
        conn.commit()
        return SessionDAO.get_by_id(session_id)

    @staticmethod
    def update_metadata(session_id: int, tags: Optional[str] = None, notes: Optional[str] = None) -> Optional[dict]:
        """Update session tags and notes."""
        conn = get_db()
        updates = []
        params = []

        if tags is not None:
            updates.append("tags = ?")
            params.append(tags)
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        if not updates:
            return SessionDAO.get_by_id(session_id)

        params.append(session_id)
        query = f"UPDATE interview_sessions SET {', '.join(updates)} WHERE id = ?"
        conn.execute(query, params)
        conn.commit()
        return SessionDAO.get_by_id(session_id)

    @staticmethod
    def delete(session_id: int) -> bool:
        """Delete a session."""
        conn = get_db()
        cursor = conn.execute("DELETE FROM interview_sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def clone_session(session_id: int, new_title: str) -> dict:
        """Clone a session for restart (copy questions list).

        Args:
            session_id: The session to clone.
            new_title: Title for the new session.

        Returns:
            The newly created session dict.
        """
        conn = get_db()

        # Get original session
        original = SessionDAO.get_by_id(session_id)
        if not original:
            raise ValueError("Original session not found")

        # Create new session with parent reference
        cursor = conn.execute(
            """INSERT INTO interview_sessions
               (title, job_role, status, parent_session_id)
               VALUES (?, ?, 'in_progress', ?)""",
            (new_title, original["job_role"], session_id),
        )
        new_session_id = cursor.lastrowid

        # Copy all questions to new session (preserve order, reset answers)
        conn.execute(
            """INSERT INTO interview_questions
               (session_id, question_id, question_text, order_index, is_followup, parent_question_id)
               SELECT ?, question_id, question_text, order_index, is_followup, parent_question_id
               FROM interview_questions
               WHERE session_id = ?
               ORDER BY order_index""",
            (new_session_id, session_id),
        )

        # Update retry count on original session
        retry_count = original.get("retry_count", 0) + 1
        conn.execute(
            "UPDATE interview_sessions SET retry_count = ? WHERE id = ?",
            (retry_count, session_id),
        )

        conn.commit()
        logger.info(f"Cloned session {session_id} to new session {new_session_id}")
        return SessionDAO.get_by_id(new_session_id)

    @staticmethod
    def delete_multiple(session_ids: list[int]) -> int:
        """Batch delete sessions.

        Args:
            session_ids: List of session IDs to delete.

        Returns:
            Count of deleted sessions.
        """
        if not session_ids:
            return 0

        conn = get_db()
        placeholders = ",".join("?" * len(session_ids))
        cursor = conn.execute(
            f"DELETE FROM interview_sessions WHERE id IN ({placeholders})",
            session_ids,
        )
        conn.commit()
        deleted = cursor.rowcount
        logger.info(f"Batch deleted {deleted} sessions")
        return deleted

    @staticmethod
    def get_multiple_with_details(session_ids: list[int]) -> list[dict]:
        """Get multiple sessions with full details for export.

        Args:
            session_ids: List of session IDs to retrieve.

        Returns:
            List of session dicts with questions and answers included.
        """
        if not session_ids:
            return []

        result = []
        for sid in session_ids:
            session = SessionDAO.get_by_id(sid)
            if session:
                # Get all questions for this session
                questions = InterviewQuestionDAO.get_by_session(sid)
                session["questions"] = questions
                result.append(session)

        return result


class InterviewQuestionDAO:
    """DAO for interview_questions table."""

    @staticmethod
    def create(
        session_id: int,
        question_text: str,
        question_id: Optional[int] = None,
        order_index: int = 0,
        is_followup: bool = False,
        parent_question_id: Optional[int] = None,
    ) -> dict:
        """Create a new interview question.

        Args:
            session_id: The session this question belongs to.
            question_text: The text of the question.
            question_id: Optional reference to the questions table.
            order_index: Position in the interview sequence.
            is_followup: Whether this is a follow-up question.
            parent_question_id: ID of the original question if this is a follow-up.
        """
        conn = get_db()
        cursor = conn.execute(
            """INSERT INTO interview_questions
               (session_id, question_id, question_text, order_index, is_followup, parent_question_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, question_id, question_text, order_index, int(is_followup), parent_question_id),
        )
        conn.commit()
        return InterviewQuestionDAO.get_by_id(cursor.lastrowid)

    @staticmethod
    def get_by_id(iq_id: int) -> Optional[dict]:
        """Get an interview question by ID."""
        conn = get_db()
        row = conn.execute("SELECT * FROM interview_questions WHERE id = ?", (iq_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_by_session(session_id: int) -> list[dict]:
        """Get all interview questions for a session."""
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM interview_questions WHERE session_id = ? ORDER BY order_index",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def submit_answer(iq_id: int, user_answer: str, ai_feedback: str, score: float) -> Optional[dict]:
        """Submit an answer with feedback."""
        conn = get_db()
        conn.execute(
            """UPDATE interview_questions
               SET user_answer = ?, ai_feedback = ?, score = ?, answered_at = CURRENT_TIMESTAMP, draft_answer = NULL
               WHERE id = ?""",
            (user_answer, ai_feedback, score, iq_id),
        )
        conn.commit()
        return InterviewQuestionDAO.get_by_id(iq_id)

    @staticmethod
    def save_draft(iq_id: int, draft_text: str) -> Optional[dict]:
        """Save answer draft for a question."""
        conn = get_db()
        conn.execute(
            "UPDATE interview_questions SET draft_answer = ? WHERE id = ?",
            (draft_text, iq_id),
        )
        conn.commit()
        return InterviewQuestionDAO.get_by_id(iq_id)

    @staticmethod
    def update_bookmark(iq_id: int, is_bookmarked: bool) -> Optional[dict]:
        """Update bookmark status for a question."""
        conn = get_db()
        conn.execute(
            "UPDATE interview_questions SET is_bookmarked = ? WHERE id = ?",
            (int(is_bookmarked), iq_id),
        )
        conn.commit()
        return InterviewQuestionDAO.get_by_id(iq_id)

    @staticmethod
    def update_note(iq_id: int, note: str) -> Optional[dict]:
        """Update note for a question."""
        conn = get_db()
        conn.execute(
            "UPDATE interview_questions SET notes = ? WHERE id = ?",
            (note, iq_id),
        )
        conn.commit()
        return InterviewQuestionDAO.get_by_id(iq_id)

    @staticmethod
    def update_time_spent(iq_id: int, time_spent: int) -> Optional[dict]:
        """Update time spent on a question."""
        conn = get_db()
        conn.execute(
            "UPDATE interview_questions SET time_spent = ? WHERE id = ?",
            (time_spent, iq_id),
        )
        conn.commit()
        return InterviewQuestionDAO.get_by_id(iq_id)

    @staticmethod
    def skip_question(iq_id: int) -> Optional[dict]:
        """Mark a question as skipped."""
        conn = get_db()
        conn.execute(
            """UPDATE interview_questions
               SET user_answer = '[SKIPPED]', score = -1, answered_at = CURRENT_TIMESTAMP, draft_answer = NULL
               WHERE id = ?""",
            (iq_id,),
        )
        conn.commit()
        return InterviewQuestionDAO.get_by_id(iq_id)

    @staticmethod
    def get_next_unanswered(session_id: int) -> Optional[dict]:
        """Get the next unanswered question in a session, excluding skipped ones."""
        conn = get_db()
        row = conn.execute(
            """SELECT * FROM interview_questions
               WHERE session_id = ? AND user_answer IS NULL AND status != 'skipped'
               ORDER BY order_index LIMIT 1""",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def update_answer(iq_id: int, user_answer: str) -> Optional[dict]:
        """Update answer and increment edit_count."""
        conn = get_db()
        conn.execute(
            """UPDATE interview_questions
               SET user_answer = ?, edit_count = edit_count + 1, answered_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (user_answer, iq_id),
        )
        conn.commit()
        return InterviewQuestionDAO.get_by_id(iq_id)

    @staticmethod
    def update_status(iq_id: int, status: str) -> Optional[dict]:
        """Update question status."""
        conn = get_db()
        conn.execute(
            "UPDATE interview_questions SET status = ? WHERE id = ?",
            (status, iq_id),
        )
        conn.commit()
        return InterviewQuestionDAO.get_by_id(iq_id)


class QuestionBankDAO:
    """DAO for question_banks table."""

    @staticmethod
    def create(name: str, description: str = "") -> dict:
        """Create a new question bank."""
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO question_banks (name, description) VALUES (?, ?)",
            (name, description),
        )
        conn.commit()
        return QuestionBankDAO.get_by_id(cursor.lastrowid)

    @staticmethod
    def get_by_id(bank_id: int) -> Optional[dict]:
        """Get a question bank by ID."""
        conn = get_db()
        row = conn.execute("SELECT * FROM question_banks WHERE id = ?", (bank_id,)).fetchone()
        if row:
            result = dict(row)
            result["question_count"] = QuestionBankDAO.count_questions(bank_id)
            return result
        return None

    @staticmethod
    def get_all(limit: int = 50, offset: int = 0) -> list[dict]:
        """Get all question banks."""
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM question_banks ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        result = []
        for row in rows:
            bank = dict(row)
            bank["question_count"] = QuestionBankDAO.count_questions(bank["id"])
            result.append(bank)
        return result

    @staticmethod
    def delete(bank_id: int) -> bool:
        """Delete a question bank."""
        conn = get_db()
        cursor = conn.execute("DELETE FROM question_banks WHERE id = ?", (bank_id,))
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def add_questions(bank_id: int, question_ids: list[int]) -> int:
        """Add questions to a bank. Returns count of newly added."""
        conn = get_db()
        added = 0
        for qid in question_ids:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO question_bank_items (bank_id, question_id) VALUES (?, ?)",
                    (bank_id, qid),
                )
                added += 1
            except sqlite3.IntegrityError as e:
                logger.warning(f"Failed to add question {qid} to bank {bank_id}, integrity error: {e}")
        conn.commit()
        return added

    @staticmethod
    def get_questions(bank_id: int, limit: int = 50, offset: int = 0) -> list[dict]:
        """Get questions in a bank with pagination."""
        conn = get_db()
        rows = conn.execute(
            """SELECT q.* FROM questions q
               JOIN question_bank_items qbi ON q.id = qbi.question_id
               WHERE qbi.bank_id = ?
               ORDER BY qbi.created_at
               LIMIT ? OFFSET ?""",
            (bank_id, limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def count_questions(bank_id: int) -> int:
        """Count questions in a bank."""
        conn = get_db()
        return conn.execute(
            "SELECT COUNT(*) FROM question_bank_items WHERE bank_id = ?",
            (bank_id,),
        ).fetchone()[0]

    @staticmethod
    def count_all() -> int:
        """Count all question banks."""
        conn = get_db()
        return conn.execute("SELECT COUNT(*) FROM question_banks").fetchone()[0]

    @staticmethod
    def update(bank_id: int, name: str, description: str) -> Optional[dict]:
        """Update a question bank."""
        conn = get_db()
        conn.execute(
            "UPDATE question_banks SET name = ?, description = ? WHERE id = ?",
            (name, description, bank_id),
        )
        conn.commit()
        return QuestionBankDAO.get_by_id(bank_id)

    @staticmethod
    def remove_question(bank_id: int, question_id: int) -> bool:
        """Remove a single question from a bank."""
        conn = get_db()
        cursor = conn.execute(
            "DELETE FROM question_bank_items WHERE bank_id = ? AND question_id = ?",
            (bank_id, question_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def remove_questions(bank_id: int, question_ids: list[int]) -> int:
        """Remove multiple questions from a bank. Returns count of removed."""
        conn = get_db()
        removed = 0
        for qid in question_ids:
            cursor = conn.execute(
                "DELETE FROM question_bank_items WHERE bank_id = ? AND question_id = ?",
                (bank_id, qid),
            )
            removed += cursor.rowcount
        conn.commit()
        return removed

    @staticmethod
    def get_available_questions(
        bank_id: int,
        category: Optional[str] = None,
        difficulty: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Get questions that are not in the bank (available for import)."""
        conn = get_db()
        query = """
            SELECT q.* FROM questions q
            WHERE q.id NOT IN (
                SELECT question_id FROM question_bank_items WHERE bank_id = ?
            )
        """
        params = [bank_id]

        if category:
            query += " AND q.category = ?"
            params.append(category)
        if difficulty:
            query += " AND q.difficulty = ?"
            params.append(difficulty)
        if search:
            query += " AND (q.title LIKE ? OR q.tags LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        query += " ORDER BY q.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def get_statistics(bank_id: int) -> dict:
        """Get statistics for a question bank."""
        conn = get_db()

        # Total count
        total = conn.execute(
            "SELECT COUNT(*) FROM question_bank_items WHERE bank_id = ?",
            (bank_id,),
        ).fetchone()[0]

        # By category
        by_category = {}
        rows = conn.execute(
            """SELECT q.category, COUNT(*) as count
               FROM questions q
               JOIN question_bank_items qbi ON q.id = qbi.question_id
               WHERE qbi.bank_id = ?
               GROUP BY q.category""",
            (bank_id,),
        ).fetchall()
        for row in rows:
            by_category[row["category"]] = row["count"]

        # By difficulty
        by_difficulty = {"easy": 0, "medium": 0, "hard": 0}
        rows = conn.execute(
            """SELECT q.difficulty, COUNT(*) as count
               FROM questions q
               JOIN question_bank_items qbi ON q.id = qbi.question_id
               WHERE qbi.bank_id = ?
               GROUP BY q.difficulty""",
            (bank_id,),
        ).fetchall()
        for row in rows:
            by_difficulty[row["difficulty"]] = row["count"]

        return {
            "total": total,
            "by_category": by_category,
            "by_difficulty": by_difficulty,
        }

    @staticmethod
    def clone(bank_id: int, new_name: str, new_description: str = "") -> dict:
        """Clone a question bank with all its questions."""
        conn = get_db()

        # Create new bank
        cursor = conn.execute(
            "INSERT INTO question_banks (name, description) VALUES (?, ?)",
            (new_name, new_description),
        )
        new_bank_id = cursor.lastrowid

        # Copy all question associations
        conn.execute(
            """INSERT INTO question_bank_items (bank_id, question_id)
               SELECT ?, question_id FROM question_bank_items WHERE bank_id = ?""",
            (new_bank_id, bank_id),
        )
        conn.commit()

        return QuestionBankDAO.get_by_id(new_bank_id)

    @staticmethod
    def batch_delete(bank_ids: list[int]) -> int:
        """Batch delete question banks. Returns count of deleted banks."""
        if not bank_ids:
            return 0

        conn = get_db()
        placeholders = ",".join("?" * len(bank_ids))
        cursor = conn.execute(
            f"DELETE FROM question_banks WHERE id IN ({placeholders})",
            bank_ids,
        )
        conn.commit()
        deleted = cursor.rowcount
        logger.info(f"Batch deleted {deleted} question banks")
        return deleted

    @staticmethod
    def batch_clone(bank_ids: list[int], name_suffix: str = " - 副本") -> list[dict]:
        """Batch clone question banks. Returns list of cloned banks."""
        cloned_banks = []
        for bank_id in bank_ids:
            bank = QuestionBankDAO.get_by_id(bank_id)
            if bank:
                new_name = bank["name"] + name_suffix
                cloned = QuestionBankDAO.clone(bank_id, new_name, bank["description"])
                cloned_banks.append(cloned)
        logger.info(f"Batch cloned {len(cloned_banks)} question banks")
        return cloned_banks

    @staticmethod
    def get_multiple_with_details(bank_ids: list[int]) -> list[dict]:
        """Get multiple banks with full details for export."""
        if not bank_ids:
            return []

        result = []
        for bid in bank_ids:
            bank = QuestionBankDAO.get_by_id(bid)
            if bank:
                questions = QuestionBankDAO.get_questions(bid, limit=10000)
                bank["questions"] = questions
                result.append(bank)
        return result


class DocumentDAO:
    """DAO for documents table."""

    @staticmethod
    def create(filename: str, file_type: str, content: str) -> dict:
        """Create a new document record."""
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO documents (filename, file_type, content) VALUES (?, ?, ?)",
            (filename, file_type, content),
        )
        conn.commit()
        return DocumentDAO.get_by_id(cursor.lastrowid)

    @staticmethod
    def get_by_id(doc_id: int) -> Optional[dict]:
        """Get a document by ID."""
        conn = get_db()
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_all(limit: int = 50, offset: int = 0) -> list[dict]:
        """Get all documents."""
        conn = get_db()
        rows = conn.execute(
            "SELECT id, filename, file_type, created_at FROM documents ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def delete(doc_id: int) -> bool:
        """Delete a document."""
        conn = get_db()
        cursor = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def get_content(doc_id: int) -> Optional[str]:
        """Get document content by ID."""
        conn = get_db()
        row = conn.execute("SELECT content FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return row["content"] if row else None


class QuestionGenerationHistoryDAO:
    """DAO for question_generation_history table."""

    @staticmethod
    def create(
        job_title: str,
        question_count: int,
        bank_id: Optional[int] = None,
        bank_name: str = "",
        jd_text: str = "",
        resume_filename: str = "",
        resume_text: str = "",
        generation_mode: str = "combined",
    ) -> dict:
        """Create a new question generation history record.

        Args:
            job_title: Target job title.
            question_count: Number of questions generated.
            bank_id: ID of the created question bank.
            bank_name: Name of the created question bank.
            jd_text: Job description text (optional).
            resume_filename: Resume filename (optional).
            resume_text: Parsed resume text (optional, for reuse).
            generation_mode: Generation mode ('resume_only', 'job_only', 'combined').
        """
        conn = get_db()
        cursor = conn.execute(
            """INSERT INTO question_generation_history
               (job_title, jd_text, resume_filename, resume_text, question_count, bank_id, bank_name, generation_mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_title, jd_text, resume_filename, resume_text, question_count, bank_id, bank_name, generation_mode),
        )
        conn.commit()
        return QuestionGenerationHistoryDAO.get_by_id(cursor.lastrowid)

    @staticmethod
    def get_by_id(history_id: int) -> Optional[dict]:
        """Get a history record by ID."""
        conn = get_db()
        row = conn.execute("SELECT * FROM question_generation_history WHERE id = ?", (history_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_all(search: Optional[str] = None, limit: int = 20, offset: int = 0) -> list[dict]:
        """Get all history records with optional search.

        Args:
            search: Search keyword (matches job_title or resume_filename).
            limit: Maximum number of records to return.
            offset: Number of records to skip.

        Returns:
            List of history records ordered by created_at DESC.
        """
        conn = get_db()
        query = "SELECT * FROM question_generation_history WHERE 1=1"
        params = []

        if search:
            query += " AND (job_title LIKE ? OR resume_filename LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def count(search: Optional[str] = None) -> int:
        """Count history records with optional search."""
        conn = get_db()
        query = "SELECT COUNT(*) FROM question_generation_history WHERE 1=1"
        params = []

        if search:
            query += " AND (job_title LIKE ? OR resume_filename LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        return conn.execute(query, params).fetchone()[0]

    @staticmethod
    def delete(history_id: int) -> bool:
        """Delete a history record."""
        conn = get_db()
        cursor = conn.execute(
            "DELETE FROM question_generation_history WHERE id = ?",
            (history_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
