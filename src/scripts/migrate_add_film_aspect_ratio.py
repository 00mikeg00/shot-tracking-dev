# migrate_add_film_aspect_ratio.py
# Adds films.aspect_ratio -- an aspect ratio PRESET (e.g. "16:9", "2.39:1")
# chosen on Create/Edit Film, not an explicit pixel resolution. Actual
# render dimensions are derived from it at render time (see
# resolve_render_dimensions() in capstone_routes.py) against a fixed base
# height, so changing the preset later doesn't require touching stored
# pixel values anywhere. Defaults to "16:9" -- the resolution
# GAAPlayblastTool_V7.py has always hardcoded, so existing films keep
# rendering identically until a coordinator picks something else.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_film_aspect_ratio.py

import sqlite3

DB_PATH = "app/database/app.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    existing = cur.execute("SELECT 1 FROM pragma_table_info('films') WHERE name = 'aspect_ratio'").fetchone()
    if existing:
        print("films.aspect_ratio already exists, skipping.")
        conn.close()
        return

    cur.execute("ALTER TABLE films ADD COLUMN aspect_ratio TEXT DEFAULT '16:9'")
    print("Added films.aspect_ratio")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
