#!/usr/bin/env python3
"""Database migration: Add status and edit_count fields to interview_questions table.

This migration adds:
- status TEXT DEFAULT 'pending' - Question status (pending/answered/skipped)
- edit_count INTEGER DEFAULT 0 - Number of times answer was edited

Usage:
    python scripts/migrate_add_status_editcount.py
"""

import sqlite3
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db_path


def check_column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def migrate():
    """Run the migration."""
    db_path = get_db_path()
    print(f"Database path: {db_path}")

    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("Starting migration: Add status and edit_count to interview_questions")

    try:
        # Check and add status field
        if not check_column_exists(cursor, "interview_questions", "status"):
            print("Adding 'status' column...")
            cursor.execute(
                "ALTER TABLE interview_questions ADD COLUMN status TEXT DEFAULT 'pending'"
            )
            print("✓ Added 'status' column")

            # Set status for existing records
            # Records with user_answer are 'answered', others are 'pending'
            cursor.execute(
                """UPDATE interview_questions
                   SET status = CASE
                       WHEN user_answer IS NOT NULL AND user_answer != '[SKIPPED]' THEN 'answered'
                       WHEN user_answer = '[SKIPPED]' THEN 'skipped'
                       ELSE 'pending'
                   END"""
            )
            updated = cursor.rowcount
            print(f"✓ Updated status for {updated} existing records")
        else:
            print("✓ Column 'status' already exists")

        # Check and add edit_count field
        if not check_column_exists(cursor, "interview_questions", "edit_count"):
            print("Adding 'edit_count' column...")
            cursor.execute(
                "ALTER TABLE interview_questions ADD COLUMN edit_count INTEGER DEFAULT 0"
            )
            print("✓ Added 'edit_count' column")

            # All existing records default to 0 (no edits)
            cursor.execute(
                "UPDATE interview_questions SET edit_count = 0 WHERE edit_count IS NULL"
            )
            updated = cursor.rowcount
            print(f"✓ Initialized edit_count for {updated} existing records")
        else:
            print("✓ Column 'edit_count' already exists")

        conn.commit()
        print("\n✅ Migration completed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
