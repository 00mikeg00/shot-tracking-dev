# migrate_add_grade_history.py
# Adds the grade_history table. save_grade_history() (app/utils/grade_utils.py)
# has been called from four places -- dashboard_routes.update_status,
# review_routes.save_annotations (x2), assignments_routes.update_assignment_status_and_crossflow
# -- and dashboard_routes.get_grade_history reads from it for the
# dashboard's "History" panel, but the table itself was never created.
# Every one of those call sites throws "no such table: grade_history"
# whenever a grade/status actually changes (same value -> same value is a
# no-op inside save_grade_history and doesn't hit this), which silently
# blocks the status update from ever reaching individual_assignment_statuses
# in dashboard_routes' case since save_grade_history is called first.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_grade_history.py

import sqlite3

DB_PATH = "app/database/app.db"  # Update path if needed

CREATE_GRADE_HISTORY = """
    CREATE TABLE IF NOT EXISTS grade_history (
        id                        INTEGER PRIMARY KEY AUTOINCREMENT,
        individual_assignment_id  INTEGER NOT NULL,
        step_id                   INTEGER NOT NULL,
        old_grade                 TEXT,
        new_grade                 TEXT,
        changed_by                INTEGER,
        changed_at                TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (individual_assignment_id) REFERENCES individual_assignments(id) ON DELETE CASCADE,
        FOREIGN KEY (step_id) REFERENCES steps(id),
        FOREIGN KEY (changed_by) REFERENCES users(id)
    )
"""

CREATE_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_grade_history_ia_id
    ON grade_history(individual_assignment_id)
"""


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        existing = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='grade_history'"
        ).fetchone()

        if existing:
            print("grade_history already exists, skipping.")
        else:
            print("Creating grade_history table...")
            cursor.execute(CREATE_GRADE_HISTORY)
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
