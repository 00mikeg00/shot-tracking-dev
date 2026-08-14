# migrate_add_step_locks.py
# Adds the step_locks table backing the GAA Save shelf button's per-step
# lock/unlock feature. A new table rather than new columns on
# individual_assignment_statuses -- see launcher_routes.py's lock/unlock
# routes for why that table isn't a safe place for this state.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_step_locks.py

import sqlite3

DB_PATH = "app/database/app.db"  # Update path if needed

CREATE_STEP_LOCKS = """
    CREATE TABLE IF NOT EXISTS step_locks (
        individual_assignment_id INTEGER NOT NULL,
        step_id                  INTEGER NOT NULL,
        locked                   INTEGER NOT NULL DEFAULT 0,
        locked_by                INTEGER,
        locked_at                TEXT,
        unlocked_by              INTEGER,
        unlocked_at              TEXT,
        PRIMARY KEY (individual_assignment_id, step_id),
        FOREIGN KEY (individual_assignment_id) REFERENCES individual_assignments(id) ON DELETE CASCADE,
        FOREIGN KEY (step_id)     REFERENCES steps(id),
        FOREIGN KEY (locked_by)   REFERENCES users(id),
        FOREIGN KEY (unlocked_by) REFERENCES users(id)
    )
"""


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        existing = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='step_locks'"
        ).fetchone()

        if existing:
            print("step_locks already exists, skipping.")
        else:
            print("Creating step_locks table...")
            cursor.execute(CREATE_STEP_LOCKS)

        conn.commit()
        print("Migration complete.")
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
