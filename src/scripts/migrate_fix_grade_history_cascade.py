# migrate_fix_grade_history_cascade.py
# Fixes a grade_history table that exists WITHOUT ON DELETE CASCADE on its
# individual_assignment_id foreign key. migrate_add_grade_history.py uses
# CREATE TABLE IF NOT EXISTS, so if grade_history already existed on a given
# server before that script's cascade clause was written, running it again
# silently no-ops instead of fixing the missing cascade -- which is exactly
# what caused "FOREIGN KEY constraint failed" when removing a student from
# a class (remove_students_from_class_db deletes individual_assignments,
# and grade_history rows referencing them had nowhere to go).
#
# SQLite can't ALTER a FK's ON DELETE behavior in place, so this rebuilds
# the table (same 7 columns as migrate_add_grade_history.py, data
# preserved) with the cascade clause added. Idempotent -- checks the
# current FK definition first and does nothing if it already cascades.
#
# Run once, from the src/ directory:
#   python scripts/migrate_fix_grade_history_cascade.py

import sqlite3

DB_PATH = "app/database/app.db"  # Update path if needed

CREATE_GRADE_HISTORY_NEW = """
    CREATE TABLE grade_history_new (
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

GRADE_HISTORY_COLUMNS = "id, individual_assignment_id, step_id, old_grade, new_grade, changed_by, changed_at"


def already_cascades(cursor):
    for row in cursor.execute("PRAGMA foreign_key_list(grade_history)").fetchall():
        # row layout: (id, seq, table, from, to, on_update, on_delete, match)
        if row[2] == "individual_assignments" and (row[6] or "").upper() == "CASCADE":
            return True
    return False


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    existing = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='grade_history'"
    ).fetchone()
    if not existing:
        print("grade_history doesn't exist yet -- nothing to fix (run migrate_add_grade_history.py instead).")
        conn.close()
        return

    if already_cascades(cursor):
        print("grade_history already cascades on individual_assignment_id, skipping.")
        conn.close()
        return

    print("grade_history exists but does NOT cascade -- rebuilding with the fix, preserving data...")
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        cursor.execute(CREATE_GRADE_HISTORY_NEW)
        cursor.execute(f"INSERT INTO grade_history_new ({GRADE_HISTORY_COLUMNS}) "
                       f"SELECT {GRADE_HISTORY_COLUMNS} FROM grade_history")
        cursor.execute("DROP TABLE grade_history")
        cursor.execute("ALTER TABLE grade_history_new RENAME TO grade_history")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_grade_history_ia_id ON grade_history(individual_assignment_id)")
        conn.commit()
        print("Migration complete -- grade_history now cascades correctly.")
    except Exception as e:
        conn.rollback()
        print(f"Migration failed, rolled back, original grade_history untouched: {e}")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()


if __name__ == "__main__":
    migrate()
