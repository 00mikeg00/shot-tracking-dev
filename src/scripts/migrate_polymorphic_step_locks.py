# migrate_polymorphic_step_locks.py
# Phase 5: generalizes step_locks from an assignment-only table
# (individual_assignment_id, step_id) into a polymorphic one
# (entity_type, entity_id, step_id) so shot-level and scene-level Layout/
# Animation/Lighting can share the same lock/unlock implementation instead
# of each getting their own copy of this table.
#
# entity_type values:
#   'assignment' -- entity_id = individual_assignments.id (existing rows,
#                   migrated as-is)
#   'shot_step'  -- entity_id = shots.id (the step itself is still step_id,
#                   matching shot_step_assignments' own (shot_id, step_id) shape)
#   'scene_step' -- entity_id = scenes.id
#
# SQLite can't express a real FOREIGN KEY on entity_id once it points at
# different tables depending on entity_type, so the ON DELETE CASCADE that
# used to come from individual_assignments(id) is gone. Callers that delete
# individual_assignments must now also manually delete their
# entity_type='assignment' step_locks rows first -- see
# remove_students_from_class_db() in app/models/classes.py, updated
# alongside this migration.
#
# Run once, from the src/ directory:
#   python scripts/migrate_polymorphic_step_locks.py

import sqlite3

DB_PATH = "app/database/app.db"  # Update path if needed

CREATE_NEW_TABLE = """
    CREATE TABLE step_locks_new (
        entity_type  TEXT    NOT NULL,
        entity_id    INTEGER NOT NULL,
        step_id      INTEGER NOT NULL,
        locked       INTEGER NOT NULL DEFAULT 0,
        locked_by    INTEGER,
        locked_at    TEXT,
        unlocked_by  INTEGER,
        unlocked_at  TEXT,
        PRIMARY KEY (entity_type, entity_id, step_id),
        FOREIGN KEY (step_id)     REFERENCES steps(id),
        FOREIGN KEY (locked_by)   REFERENCES users(id),
        FOREIGN KEY (unlocked_by) REFERENCES users(id)
    )
"""


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        already_polymorphic = cursor.execute("""
            SELECT 1 FROM pragma_table_info('step_locks') WHERE name = 'entity_type'
        """).fetchone()
        if already_polymorphic:
            print("step_locks is already polymorphic, skipping.")
            return

        old_exists = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='step_locks'"
        ).fetchone()

        print("Creating step_locks_new...")
        cursor.execute(CREATE_NEW_TABLE)

        if old_exists:
            print("Migrating existing rows as entity_type='assignment'...")
            cursor.execute("""
                INSERT INTO step_locks_new
                    (entity_type, entity_id, step_id, locked, locked_by, locked_at, unlocked_by, unlocked_at)
                SELECT
                    'assignment', individual_assignment_id, step_id, locked, locked_by, locked_at, unlocked_by, unlocked_at
                FROM step_locks
            """)
            print(f"Migrated {cursor.rowcount} row(s).")
            cursor.execute("DROP TABLE step_locks")

        cursor.execute("ALTER TABLE step_locks_new RENAME TO step_locks")

        conn.commit()
        print("Migration complete.")
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
