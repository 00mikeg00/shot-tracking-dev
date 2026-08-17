# migrate_add_step_checkouts.py
# Adds step_checkouts, tracking who currently has a step's Maya file OPEN
# (in progress), separate from step_locks (which means "approved," not
# "in use"). Introduced for the Character/Rigs Texture-Surface/Rigging
# mutual-exclusion rule: those two steps no longer gate each other's
# approval (see resolve_current_step()'s parallel-group handling), but
# they share one continuous version lineage on disk (see Assets.py's
# header comment), so only one of them may be open at a time -- this
# table is what enforces that.
#
# heartbeat_at (bumped periodically while Maya has the file open, see
# Assets.py) lets the server treat a checkout as abandoned and ignore it
# once it's stale (Maya crashed without checking in), instead of
# permanently blocking the sibling step. No cron needed -- staleness is
# just a read-time comparison against heartbeat_at.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_step_checkouts.py

import sqlite3

DB_PATH = "app/database/app.db"

CREATE_TABLE = """
    CREATE TABLE step_checkouts (
        entity_type     TEXT    NOT NULL,
        entity_id       INTEGER NOT NULL,
        step_id         INTEGER NOT NULL,
        checked_out_by  INTEGER NOT NULL,
        checked_out_at  TEXT    NOT NULL,
        heartbeat_at    TEXT    NOT NULL,
        PRIMARY KEY (entity_type, entity_id, step_id),
        FOREIGN KEY (step_id)        REFERENCES steps(id),
        FOREIGN KEY (checked_out_by) REFERENCES users(id)
    )
"""


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        exists = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='step_checkouts'"
        ).fetchone()
        if exists:
            print("step_checkouts already exists, skipping.")
            return

        print("Creating step_checkouts...")
        cursor.execute(CREATE_TABLE)

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
