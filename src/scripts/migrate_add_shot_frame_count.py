# migrate_add_shot_frame_count.py
# Adds shots.frame_count -- an Editable-anytime (no lock, unlike
# camera_framing) per-shot frame count authored by the Layout Coordinator
# on the Edit Layout Config page. Seeds the shot's frame range (1 to
# frame_count) into Maya's playbackOptions every time CapstoneLayout.py/
# CapstoneAnimation.py opens or creates a scene for that shot -- not just at
# creation -- so later revisions actually propagate.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_shot_frame_count.py

import sqlite3

DB_PATH = "app/database/app.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    existing = cur.execute("SELECT 1 FROM pragma_table_info('shots') WHERE name = 'frame_count'").fetchone()
    if existing:
        print("shots.frame_count already exists, skipping.")
        conn.close()
        return

    cur.execute("ALTER TABLE shots ADD COLUMN frame_count INTEGER")
    print("Added shots.frame_count")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
