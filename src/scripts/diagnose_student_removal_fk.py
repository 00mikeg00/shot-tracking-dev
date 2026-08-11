# diagnose_student_removal_fk.py
# Read-only diagnostic for "FOREIGN KEY constraint failed" when removing a
# student from a class (models/classes.py remove_students_from_class_db).
# That function only manually deletes individual_assignment_statuses before
# deleting individual_assignments -- every other table that references
# individual_assignments(id) is expected to have ON DELETE CASCADE, but if
# any of them don't (schema drift between environments, or a table created
# before its cascade clause was added), the DELETE FROM individual_assignments
# fails with exactly this error and SQLite doesn't say which table.
#
# This lists every table with a FK to individual_assignments(id), whether
# that FK cascades, and how many rows would currently block a delete for
# the given class + student(s).
#
# Run from the src/ directory:
#   python scripts/diagnose_student_removal_fk.py <class_id> <student_id> [<student_id2> ...]

import sqlite3
import sys

DB_PATH = "app/database/app.db"  # Update path if needed


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/diagnose_student_removal_fk.py <class_id> <student_id> [<student_id2> ...]")
        sys.exit(1)

    class_id = sys.argv[1]
    student_ids = sys.argv[2:]

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    placeholders_students = ",".join("?" * len(student_ids))
    ia_rows = cursor.execute(f"""
        SELECT id FROM individual_assignments
        WHERE users_id IN ({placeholders_students})
          AND assignment_id IN (SELECT id FROM assignments WHERE class_id = ?)
    """, [*student_ids, class_id]).fetchall()
    ia_ids = [r["id"] for r in ia_rows]

    print(f"individual_assignments that would be deleted: {ia_ids}")
    if not ia_ids:
        print("No matching individual_assignments found for this class/student combination -- nothing to check.")
        return

    # Every table with a column literally named individual_assignment_id,
    # found generically instead of hardcoded so this stays accurate if more
    # tables get added later.
    tables = [row["name"] for row in cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND sql LIKE '%individual_assignment_id%'
    """).fetchall()]

    placeholders_ia = ",".join("?" * len(ia_ids))
    print(f"\nChecking {len(tables)} table(s) with an individual_assignment_id column:\n")

    # remove_students_from_class_db() already deletes individual_assignment_statuses
    # manually before touching individual_assignments -- it showing up here as
    # non-cascading is expected and NOT itself the bug. Any OTHER non-cascading
    # table with matching rows is the real smoking gun.
    already_handled = {"individual_assignment_statuses"}

    any_blockers = False
    for table in tables:
        fk_list = cursor.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        cascades = any(
            fk["table"] == "individual_assignments" and (fk["on_delete"] or "").upper() == "CASCADE"
            for fk in fk_list
        )
        count = cursor.execute(f"""
            SELECT COUNT(*) AS n FROM {table} WHERE individual_assignment_id IN ({placeholders_ia})
        """, ia_ids).fetchone()["n"]

        is_real_blocker = not cascades and count > 0 and table not in already_handled
        if is_real_blocker:
            any_blockers = True
            status = "NO CASCADE -- will block delete"
        elif not cascades and count > 0:
            status = "no cascade, but already deleted manually by remove_students_from_class_db -- OK"
        elif not cascades:
            status = "no cascade, but no matching rows -- OK"
        else:
            status = "OK (cascades)"
        flag = " <-- REAL BLOCKER" if is_real_blocker else ""
        print(f"  {table:35s} rows_matching={count:<4d} cascade={'yes' if cascades else 'no':<4s} {status}{flag}")

    print()
    if any_blockers:
        print("Found the blocker(s) above (marked REAL BLOCKER). Fix is either: add ON DELETE CASCADE")
        print("to that table's FK (requires recreating the table in SQLite), or delete matching rows")
        print("from it manually in remove_students_from_class_db() before the individual_assignments")
        print("DELETE, same as individual_assignment_statuses already does.")
    else:
        print("No unexpected non-cascading blockers found among individual_assignment_id tables.")
        print("The FK violation may be coming from a different relationship (e.g. a table that")
        print("references individual_assignments(id) without a column literally named")
        print("individual_assignment_id) -- share the full traceback or the exact student/class")
        print("used and I'll dig further.")

    conn.close()


if __name__ == "__main__":
    main()
