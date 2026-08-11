# migrate_add_layout_config.py
# Phase 5 addendum: scene/shot asset config editor + camera framing.
#
# 1. Adds shots.camera_framing (TEXT) -- no existing column fits (see
#    investigation: description is free text already used for shot
#    descriptions elsewhere, not safe to repurpose).
# 2. Adds a "Layout Coordinator" row to groups (section='films',
#    permission_level=2) -- same tier/pattern as the existing
#    "Storyboard Coordinator"/"Animation Coordinator"/etc rows, assignable
#    per-film via film_crew like any of them. Not a new role: it's granted
#    the same way those are (a second film_crew row for a user who already
#    has another role, e.g. a UPM), per the design doc's explicit ask.
#
# scene_assets (scene_id, asset_id, notes, asset_type) already exists in
# app.db with 0 rows and no code referencing it -- reused as-is for
# scene-level asset assignments, no schema change needed there.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_layout_config.py

import sqlite3

DB_PATH = "app/database/app.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cols = [row[1] for row in cur.execute("PRAGMA table_info(shots)").fetchall()]
    if "camera_framing" not in cols:
        cur.execute("ALTER TABLE shots ADD COLUMN camera_framing TEXT")
        print("Added shots.camera_framing")
    else:
        print("shots.camera_framing already exists, skipping")

    existing = cur.execute(
        "SELECT id FROM groups WHERE name = ? AND section = 'films'",
        ("Layout Coordinator",)
    ).fetchone()
    if existing:
        print(f"'Layout Coordinator' group already exists (id={existing[0]}), skipping")
    else:
        cur.execute(
            "INSERT INTO groups (name, permission_level, section) VALUES (?, ?, ?)",
            ("Layout Coordinator", 2, "films")
        )
        print(f"Inserted 'Layout Coordinator' group (id={cur.lastrowid})")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
