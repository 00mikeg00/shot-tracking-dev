# migrate_add_assignment_frame_range.py
# Adds frame_start / frame_end columns to assignments so the New/Edit
# Assignment forms can capture a frame range for the upcoming X-sheet feature.
#
# Also backfills max_points, which add_assignment_to_db() (app/models/__init__.py)
# and several read queries (review_routes.py, classes.copy_assignments_from_class)
# already expect to exist on assignments, but which was never added to this DB --
# every "Add Assignment" submission was failing with
# "table assignments has no column named max_points" until this ran.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_assignment_frame_range.py

import sqlite3

DB_PATH = "app/database/app.db"  # Update path if needed


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(assignments)")}

    try:
        if "frame_start" not in existing_cols:
            print("Adding frame_start column...")
            cursor.execute("ALTER TABLE assignments ADD COLUMN frame_start INTEGER")
        else:
            print("frame_start already exists, skipping.")

        if "frame_end" not in existing_cols:
            print("Adding frame_end column...")
            cursor.execute("ALTER TABLE assignments ADD COLUMN frame_end INTEGER")
        else:
            print("frame_end already exists, skipping.")

        if "max_points" not in existing_cols:
            print("Adding max_points column...")
            cursor.execute("ALTER TABLE assignments ADD COLUMN max_points INTEGER")
        else:
            print("max_points already exists, skipping.")

        conn.commit()
        print("Migration complete.")
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
