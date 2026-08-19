# migrate_add_class_locked.py
# Adds classes.locked, backing the "lock this class" safety toggle that
# prevents accidental deletion. Only Instructor/Admin can lock/unlock or
# delete (see role_required('classes', ['Instructor', 'Admin']) on the
# classes routes) -- the flag just adds a deliberate extra step before a
# locked class can be deleted.
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_class_locked.py

import sqlite3

DB_PATH = "app/database/app.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    existing = cur.execute(
        "SELECT 1 FROM pragma_table_info('classes') WHERE name = 'locked'"
    ).fetchone()

    if existing:
        print("classes.locked already exists, skipping.")
        conn.close()
        return

    cur.execute("ALTER TABLE classes ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    conn.close()
    print("Migration complete: added classes.locked")


if __name__ == "__main__":
    main()
