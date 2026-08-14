# migrate_drop_xsheet_snapshot_tables.py
# Drops xsheet_snapshots / xsheet_annotations -- "Share for Feedback" no
# longer uses a bespoke snapshot+annotation system. It now saves the
# captured sheet straight into planning_files (same table hand-drawn
# Planning pages use), so it shows up in the existing Markup Sidebar and
# gets annotated/reviewed through review_routes.py's save_annotations,
# same as any other planning drawing. These two tables are dead.
#
# Run once, from the src/ directory:
#   python scripts/migrate_drop_xsheet_snapshot_tables.py

import sqlite3

DB_PATH = "app/database/app.db"  # Update path if needed


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        for table_name in ("xsheet_annotations", "xsheet_snapshots"):
            existing = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
            ).fetchone()
            if existing:
                print(f"Dropping {table_name}...")
                cursor.execute(f"DROP TABLE {table_name}")
            else:
                print(f"{table_name} already gone, skipping.")

        conn.commit()
        print("Migration complete.")
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
