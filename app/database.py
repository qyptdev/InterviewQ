"""SQLite database connection and initialization."""

import sqlite3
import os
from threading import local

_db_local = local()

DB_SCHEMA = """
-- Questions table
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '技术',
    difficulty TEXT NOT NULL DEFAULT 'medium',
    tags TEXT DEFAULT '',
    expected_answer TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Auto-update updated_at trigger
CREATE TRIGGER IF NOT EXISTS trg_questions_updated_at
    AFTER UPDATE ON questions
    FOR EACH ROW
BEGIN
    UPDATE questions SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;

-- Interview sessions
CREATE TABLE IF NOT EXISTS interview_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    job_role TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'in_progress',
    paused_at TIMESTAMP,
    tags TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    parent_session_id INTEGER DEFAULT NULL,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (parent_session_id) REFERENCES interview_sessions(id) ON DELETE SET NULL
);

-- Interview Q&A records
CREATE TABLE IF NOT EXISTS interview_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    question_id INTEGER,
    question_text TEXT NOT NULL,
    user_answer TEXT,
    draft_answer TEXT DEFAULT '',
    ai_feedback TEXT,
    score REAL,
    time_spent INTEGER DEFAULT 0,
    is_bookmarked INTEGER NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    order_index INTEGER NOT NULL DEFAULT 0,
    is_followup INTEGER NOT NULL DEFAULT 0,
    parent_question_id INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    edit_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    answered_at TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE SET NULL,
    FOREIGN KEY (parent_question_id) REFERENCES interview_questions(id) ON DELETE SET NULL
);

-- Question banks
CREATE TABLE IF NOT EXISTS question_banks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Question-bank mapping
CREATE TABLE IF NOT EXISTS question_bank_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_id) REFERENCES question_banks(id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
    UNIQUE(bank_id, question_id)
);

-- Documents table
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Question generation history
CREATE TABLE IF NOT EXISTS question_generation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_title TEXT NOT NULL,
    jd_text TEXT DEFAULT '',
    resume_filename TEXT DEFAULT '',
    resume_text TEXT DEFAULT '',
    question_count INTEGER NOT NULL,
    bank_id INTEGER,
    bank_name TEXT DEFAULT '',
    generation_mode TEXT DEFAULT 'combined',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_id) REFERENCES question_banks(id) ON DELETE SET NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category);
CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty);
CREATE INDEX IF NOT EXISTS idx_interview_questions_session ON interview_questions(session_id);
CREATE INDEX IF NOT EXISTS idx_interview_sessions_status ON interview_sessions(status);
CREATE INDEX IF NOT EXISTS idx_question_bank_items_bank ON question_bank_items(bank_id);
CREATE INDEX IF NOT EXISTS idx_question_bank_items_question ON question_bank_items(question_id);
CREATE INDEX IF NOT EXISTS idx_generation_history_created_at ON question_generation_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_history_job_title ON question_generation_history(job_title);
"""


def get_db_path() -> str:
    """Get the database file path from environment."""
    from app.config import get_settings

    settings = get_settings()
    db_url = settings.database_url
    # Parse sqlite:///path format
    path = db_url.replace("sqlite:///", "")
    if not path:
        path = "./data/interview.db"
    return path


def get_db() -> sqlite3.Connection:
    """Get the current thread's database connection."""
    if not hasattr(_db_local, "conn") or _db_local.conn is None:
        db_path = get_db_path()
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        _db_local.conn = sqlite3.connect(db_path)
        _db_local.conn.row_factory = sqlite3.Row
        _db_local.conn.execute("PRAGMA journal_mode=WAL")
        _db_local.conn.execute("PRAGMA foreign_keys=ON")
    return _db_local.conn


def init_db() -> None:
    """Initialize the database, creating all tables."""
    conn = get_db()
    conn.executescript(DB_SCHEMA)
    conn.commit()

    # Apply migrations for existing databases
    _apply_migrations(conn)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply database migrations for schema evolution."""
    # Check if parent_session_id column exists in interview_sessions
    cursor = conn.execute("PRAGMA table_info(interview_sessions)")
    session_columns = [row[1] for row in cursor.fetchall()]

    if "parent_session_id" not in session_columns:
        conn.execute(
            "ALTER TABLE interview_sessions "
            "ADD COLUMN parent_session_id INTEGER DEFAULT NULL"
        )
        conn.commit()

    if "retry_count" not in session_columns:
        conn.execute(
            "ALTER TABLE interview_sessions "
            "ADD COLUMN retry_count INTEGER DEFAULT 0"
        )
        conn.commit()

    # Check if status and edit_count columns exist in interview_questions
    cursor = conn.execute("PRAGMA table_info(interview_questions)")
    question_columns = [row[1] for row in cursor.fetchall()]

    if "status" not in question_columns:
        conn.execute(
            "ALTER TABLE interview_questions "
            "ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
        )
        conn.commit()

    if "edit_count" not in question_columns:
        conn.execute(
            "ALTER TABLE interview_questions "
            "ADD COLUMN edit_count INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()


def close_db() -> None:
    """Close the current thread's database connection."""
    if hasattr(_db_local, "conn") and _db_local.conn is not None:
        _db_local.conn.close()
        _db_local.conn = None
