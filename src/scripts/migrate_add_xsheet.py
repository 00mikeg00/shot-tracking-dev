# migrate_add_xsheet.py
# Adds the X-sheet (digital exposure sheet) feature's storage:
#   - frame_start / frame_end on individual_assignments, copied once from
#     assignments.frame_start/frame_end at individual-assignment creation
#     time (see add_assignment_to_db() / add_individual_assignment() in
#     app/models/__init__.py) and never re-read afterward.
#   - xsheet_columns / xsheet_rows / xsheet_symbols / xsheet_snapshots /
#     xsheet_annotations, all scoped by individual_assignment_id -- same
#     single-FK convention as planning_files / video_reference_files,
#     since individual_assignments already ties one student to one
#     assignment (no separate assignment_id + student_id pair needed).
#
# Run once, from the src/ directory:
#   python scripts/migrate_add_xsheet.py

import sqlite3

DB_PATH = "app/database/app.db"  # Update path if needed

CREATE_XSHEET_COLUMNS = """
    CREATE TABLE IF NOT EXISTS xsheet_columns (
        id                        INTEGER PRIMARY KEY AUTOINCREMENT,
        individual_assignment_id  INTEGER NOT NULL,
        column_key                TEXT NOT NULL,
        display_name              TEXT NOT NULL,
        category                  TEXT NOT NULL,
        display_order             INTEGER NOT NULL,
        locked                    INTEGER NOT NULL DEFAULT 0,
        UNIQUE(individual_assignment_id, column_key),
        FOREIGN KEY (individual_assignment_id) REFERENCES individual_assignments(id) ON DELETE CASCADE
    )
"""

CREATE_XSHEET_ROWS = """
    CREATE TABLE IF NOT EXISTS xsheet_rows (
        id                        INTEGER PRIMARY KEY AUTOINCREMENT,
        individual_assignment_id  INTEGER NOT NULL,
        frame                     INTEGER NOT NULL,
        data                      TEXT NOT NULL DEFAULT '{}',
        UNIQUE(individual_assignment_id, frame),
        FOREIGN KEY (individual_assignment_id) REFERENCES individual_assignments(id) ON DELETE CASCADE
    )
"""

CREATE_XSHEET_SYMBOLS = """
    CREATE TABLE IF NOT EXISTS xsheet_symbols (
        id                        INTEGER PRIMARY KEY AUTOINCREMENT,
        individual_assignment_id  INTEGER NOT NULL,
        column_key                TEXT NOT NULL,
        frame_start               INTEGER NOT NULL,
        frame_end                 INTEGER NOT NULL,
        symbol_type               TEXT NOT NULL CHECK(symbol_type IN ('hold', 'accent')),
        direction                 TEXT CHECK(direction IN ('up', 'down', 'settle')),
        FOREIGN KEY (individual_assignment_id) REFERENCES individual_assignments(id) ON DELETE CASCADE
    )
"""

CREATE_XSHEET_SNAPSHOTS = """
    CREATE TABLE IF NOT EXISTS xsheet_snapshots (
        id                        INTEGER PRIMARY KEY AUTOINCREMENT,
        individual_assignment_id  INTEGER NOT NULL,
        version                   INTEGER NOT NULL,
        image_path                TEXT NOT NULL,
        created_at                TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(individual_assignment_id, version),
        FOREIGN KEY (individual_assignment_id) REFERENCES individual_assignments(id) ON DELETE CASCADE
    )
"""

CREATE_XSHEET_ANNOTATIONS = """
    CREATE TABLE IF NOT EXISTS xsheet_annotations (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id   INTEGER NOT NULL,
        instructor_id INTEGER NOT NULL,
        strokes       TEXT NOT NULL,
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (snapshot_id) REFERENCES xsheet_snapshots(id) ON DELETE CASCADE,
        FOREIGN KEY (instructor_id) REFERENCES users(id)
    )
"""

INDEXES = [
    ("idx_xsheet_columns_ia_id", "xsheet_columns", "individual_assignment_id"),
    ("idx_xsheet_rows_ia_id", "xsheet_rows", "individual_assignment_id"),
    ("idx_xsheet_symbols_ia_id", "xsheet_symbols", "individual_assignment_id"),
    ("idx_xsheet_snapshots_ia_id", "xsheet_snapshots", "individual_assignment_id"),
    ("idx_xsheet_annotations_snapshot_id", "xsheet_annotations", "snapshot_id"),
]

TABLES = [
    ("xsheet_columns", CREATE_XSHEET_COLUMNS),
    ("xsheet_rows", CREATE_XSHEET_ROWS),
    ("xsheet_symbols", CREATE_XSHEET_SYMBOLS),
    ("xsheet_snapshots", CREATE_XSHEET_SNAPSHOTS),
    ("xsheet_annotations", CREATE_XSHEET_ANNOTATIONS),
]


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        existing_ia_cols = {row[1] for row in cursor.execute("PRAGMA table_info(individual_assignments)")}

        if "frame_start" not in existing_ia_cols:
            print("Adding individual_assignments.frame_start column...")
            cursor.execute("ALTER TABLE individual_assignments ADD COLUMN frame_start INTEGER")
        else:
            print("individual_assignments.frame_start already exists, skipping.")

        if "frame_end" not in existing_ia_cols:
            print("Adding individual_assignments.frame_end column...")
            cursor.execute("ALTER TABLE individual_assignments ADD COLUMN frame_end INTEGER")
        else:
            print("individual_assignments.frame_end already exists, skipping.")

        for table_name, create_sql in TABLES:
            existing = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
            ).fetchone()
            if existing:
                print(f"{table_name} already exists, skipping.")
            else:
                print(f"Creating {table_name} table...")
                cursor.execute(create_sql)

        for index_name, table_name, column_name in INDEXES:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({column_name})")

        conn.commit()
        print("Migration complete.")
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
