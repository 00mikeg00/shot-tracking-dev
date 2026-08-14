# migrate_add_assignment_starter_scene.py
# Adds assignment_config_presets.starter_scene -- an optional full path to
# a pre-built .ma/.mb file a coordinator wants students to open instead of
# a blank scene (e.g. a shot already blocked in, or set dressing already
# placed). Lives outside the class's normal Assignments/Scenes folder
# (students browse that for their own versioned files) -- see
# Assignments.py's create_or_continue_step()/open_or_create_step()/
# _run_flat(), which copy this file into the student's own v1 path and
# open the copy, same "copy in, then open the copy" pattern
# CapstoneLayout.py already uses for scene Layout -> shot Layout.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_assignment_starter_scene.py

import sqlite3

DB_PATH = "app/database/app.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    existing = cur.execute(
        "SELECT 1 FROM pragma_table_info('assignment_config_presets') WHERE name = 'starter_scene'"
    ).fetchone()
    if existing:
        print("assignment_config_presets.starter_scene already exists, skipping.")
        conn.close()
        return

    cur.execute("ALTER TABLE assignment_config_presets ADD COLUMN starter_scene TEXT")
    print("Added assignment_config_presets.starter_scene")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
