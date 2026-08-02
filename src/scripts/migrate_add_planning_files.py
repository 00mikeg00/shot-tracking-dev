# migrate_add_planning_files.py
# Adds the planning_files table backing the Planning step's "Planning
# drawings" upload (student-uploaded sketch/thumbnail stills). Unlike
# video/film review files, these aren't discovered by scanning a folder +
# filename convention -- there can be multiple current files per
# individual_assignment_id, so we need real metadata (uploader, order,
# timestamp) instead of parsing it back out of filenames. See
# get_review_files() in review_routes.py, which merges these rows into
# the same fileList shape the Markup tool Sidebar already consumes.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_planning_files.py

import sqlite3

DB_PATH = "app/database/app.db"  # Update path if needed

CREATE_PLANNING_FILES = """
    CREATE TABLE IF NOT EXISTS planning_files (
        id                        INTEGER PRIMARY KEY AUTOINCREMENT,
        individual_assignment_id  INTEGER NOT NULL,
        uploaded_by_user_id       INTEGER NOT NULL,
        file_path                 TEXT NOT NULL,
        file_name                 TEXT NOT NULL,
        page_order                INTEGER NOT NULL DEFAULT 0,
        uploaded_at                TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (individual_assignment_id) REFERENCES individual_assignments(id) ON DELETE CASCADE,
        FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id)
    )
"""

CREATE_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_planning_files_ia_id
    ON planning_files(individual_assignment_id)
"""


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        existing = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='planning_files'"
        ).fetchone()

        if existing:
            print("planning_files already exists, skipping.")
        else:
            print("Creating planning_files table...")
            cursor.execute(CREATE_PLANNING_FILES)
            cursor.execute(CREATE_INDEX)

        conn.commit()
        print("Migration complete.")
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
