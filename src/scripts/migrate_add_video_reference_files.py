# migrate_add_video_reference_files.py
# Adds the video_reference_files table backing the Planning step's "Video
# reference" sub-component -- students either upload their own reference
# clip (transcoded to webm to keep it small) or paste a link to an
# external video (e.g. something found online). Both are reference
# material the instructor views while grading the Planning step as a
# whole (drawings + video reference + x-sheet all feed one grade) -- see
# planning_files for the sibling "Planning drawings" table this mirrors.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_video_reference_files.py

import sqlite3

DB_PATH = "app/database/app.db"  # Update path if needed

CREATE_VIDEO_REFERENCE_FILES = """
    CREATE TABLE IF NOT EXISTS video_reference_files (
        id                        INTEGER PRIMARY KEY AUTOINCREMENT,
        individual_assignment_id  INTEGER NOT NULL,
        uploaded_by_user_id       INTEGER NOT NULL,
        source_type               TEXT NOT NULL CHECK(source_type IN ('upload', 'link')),
        file_path                 TEXT,
        file_name                 TEXT,
        external_url              TEXT,
        conversion_status         TEXT NOT NULL DEFAULT 'pending',
        uploaded_at                TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (individual_assignment_id) REFERENCES individual_assignments(id) ON DELETE CASCADE,
        FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id)
    )
"""

CREATE_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_video_reference_files_ia_id
    ON video_reference_files(individual_assignment_id)
"""


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        existing = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='video_reference_files'"
        ).fetchone()

        if existing:
            print("video_reference_files already exists, skipping.")
        else:
            print("Creating video_reference_files table...")
            cursor.execute(CREATE_VIDEO_REFERENCE_FILES)
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
