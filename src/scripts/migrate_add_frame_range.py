# migrate_add_frame_range.py
# Adds frame_start / frame_end columns to assignment_config_presets so the
# semester config admin UI can store a per-assignment frame range alongside
# the existing rigs/camera/filename preset data.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_frame_range.py

import sqlite3

DB_PATH = "app/database/app.db"  # Update path if needed


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(assignment_config_presets)")}

    try:
        if "frame_start" not in existing_cols:
            print("Adding frame_start column...")
            cursor.execute("ALTER TABLE assignment_config_presets ADD COLUMN frame_start INTEGER")
        else:
            print("frame_start already exists, skipping.")

        if "frame_end" not in existing_cols:
            print("Adding frame_end column...")
            cursor.execute("ALTER TABLE assignment_config_presets ADD COLUMN frame_end INTEGER")
        else:
            print("frame_end already exists, skipping.")

        conn.commit()
        print("Migration complete.")
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
