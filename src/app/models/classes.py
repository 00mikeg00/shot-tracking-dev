import os
from flask import url_for, flash
from app.database.db import get_db
import sqlite3
from app.models.user_model import User

BASE_CLASS_FOLDER = r"\\gaaap1prd01w.ad.uc.edu\Classes"

# ----------------------------------------------------------------------------------
# RETRIEVAL
# ----------------------------------------------------------------------------------

def query_classes(filters=None):
    query = "SELECT * FROM classes"
    params = []
    if filters:
        conditions = []
        for key, value in filters.items():
            conditions.append(f"{key} = ?")
            params.append(value)
        query += " WHERE " + " AND ".join(conditions)

    conn = get_db()
    try:
        return [dict(row) for row in conn.execute(query, params)]
    except Exception as e:
        print(f"Error querying classes: {e}")
        raise e

def get_all_classes(minimal=False):
    conn = get_db()

    if minimal:
        query = """
        SELECT c.id, 
               s.year || ' ' || s.term || ' ' || c.code || ' - ' || c.class_name AS full_class_name 
        FROM classes c
        JOIN semesters s ON c.semester_id = s.id
        ORDER BY s.year, 
                 CASE s.term
                    WHEN 'Spring' THEN 1
                    WHEN 'Summer' THEN 2
                    WHEN 'Fall' THEN 3
                 END
        """
    else:
        query = """
        SELECT 
            c.id,
            s.year,
            s.term AS semester,
            c.code,
            c.class_number,
            c.class_name,
            c.instructor_id,
            u.name AS instructor_name,
            s.year || ' - ' || s.term || ' - ' || c.code || ' ' || c.class_number || ' - ' || c.class_name AS full_class_name
        FROM classes c
        JOIN semesters s ON c.semester_id = s.id
        LEFT JOIN users u ON c.instructor_id = u.id
        ORDER BY s.year, 
                 CASE s.term
                    WHEN 'Spring' THEN 1
                    WHEN 'Summer' THEN 2
                    WHEN 'Fall' THEN 3
                 END
        """

    return [dict(row) for row in conn.execute(query)]

def get_all_classes_minimal(conn):
    query = """
        SELECT 
            c.id,
            c.code,
            c.class_number,
            c.class_name,
            c.instructor_id,
            s.term AS semester,
            s.year,
            u.name AS instructor_name,
            s.year || ' - ' || s.term || ' - ' || c.code || ' ' || c.class_number || ' - ' || c.class_name AS full_class_name
        FROM classes c
        LEFT JOIN users u ON c.instructor_id = u.id
        LEFT JOIN semesters s ON c.semester_id = s.id
        WHERE c.archived = 0
        ORDER BY s.year DESC,
                CASE s.term
                    WHEN 'Spring' THEN 1
                    WHEN 'Summer' THEN 2
                    WHEN 'Fall' THEN 3
                END
    """
    try:
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows] if rows else []
    except Exception as e:
        print(f"Error fetching class data: {e}")
        return []

def serialize_classes_for_dropdown():
    conn = get_db()
    return [
        {
            "id": cls['id'],
            "name": cls['full_class_name'],
            "url": url_for('assignments.view_assignments', class_id=cls['id'])
        }
        for cls in get_all_classes_minimal(conn)
    ]

def get_class_by_id(class_id):
    query = "SELECT * FROM classes WHERE id = ?"
    conn = get_db()
    try:
        result = conn.execute(query, (class_id,)).fetchone()
        return dict(result) if result else None
    except Exception as e:
        raise RuntimeError(f"Error fetching class with ID {class_id}: {e}")

def get_all_classes_dict():
    db = get_db()
    rows = db.execute("""
        SELECT c.id, c.class_name, c.code, c.class_number,
               s.year, s.term AS semester_name,
               u.name AS instructor_name
        FROM classes c
        JOIN semesters s ON c.semester_id = s.id
        LEFT JOIN users u ON c.instructor_id = u.id
        WHERE c.archived = 0
        ORDER BY s.year DESC,
                 CASE s.term
                    WHEN 'Spring' THEN 1
                    WHEN 'Summer' THEN 2
                    WHEN 'Fall' THEN 3
                 END
    """).fetchall()

    grouped = {}
    for row in rows:
        semester_label = f"{row['year']} - {row['semester_name']}"
        grouped.setdefault(semester_label, []).append({
            'id': row['id'],
            'class_name': row['class_name'],
            'code': row['code'],
            'class_number': row['class_number'],
            'year': row['year'],
            'semester': row['semester_name'],
            'instructor_name': row['instructor_name']
        })

    return grouped



def fetch_unique_class_names():
    db = get_db()
    rows = db.execute("SELECT DISTINCT class_name FROM classes ORDER BY class_name").fetchall()
    return [row["class_name"] for row in rows]


def get_class_folder_path(semester_label: str, class_name: str) -> str:
    return os.path.join(BASE_CLASS_FOLDER, semester_label, class_name)


# ----------------------------------------------------------------------------------
# VALIDATION
# ----------------------------------------------------------------------------------

def validate_class_exists(class_id):
    class_details = get_class_by_id(class_id)
    if not class_details:
        flash({'type': 'error', 'message': 'Class not found.'})
        return None
    return class_details

def validate_class_number(class_number):
    if not class_number.isdigit():
        raise ValueError(f"Invalid class number: {class_number} (must be all digits)")
    if len(class_number) > 4:
        raise ValueError(f"Invalid class number: {class_number} (must be up to 4 digits)")
    if int(class_number) <= 0:
        raise ValueError(f"Invalid class number: {class_number} (must be greater than zero)")

# ----------------------------------------------------------------------------------
# DELETION
# ----------------------------------------------------------------------------------

def delete_classes(class_ids):
    for class_id in class_ids:
        delete_class_by_id(class_id)

def delete_class_by_id(class_id):
    db = get_db()
    db.execute("PRAGMA foreign_keys = ON")
    try:
        # Remove grade history (must go before individual_assignments)
        db.execute("""
            DELETE FROM grade_history 
            WHERE individual_assignment_id IN (
                SELECT id FROM individual_assignments 
                WHERE assignment_id IN (
                    SELECT id FROM assignments WHERE class_id = ?
                )
            )
        """, (class_id,))

        # Remove individual assignment statuses
        db.execute("""
            DELETE FROM individual_assignment_statuses 
            WHERE individual_assignment_id IN (
                SELECT id FROM individual_assignments 
                WHERE assignment_id IN (
                    SELECT id FROM assignments WHERE class_id = ?
                )
            )
        """, (class_id,))

        # Remove individual assignments
        db.execute("""
            DELETE FROM individual_assignments 
            WHERE assignment_id IN (
                SELECT id FROM assignments WHERE class_id = ?
            )
        """, (class_id,))

        # Remove class enrollments
        db.execute("DELETE FROM class_enrollments WHERE class_id = ?", (class_id,))

        # Finally, delete the class
        # Get class info before deleting (to locate the folder)
        class_info = db.execute("""
            SELECT c.class_name, s.year || '-' || s.term AS semester
            FROM classes c
            JOIN semesters s ON s.id = c.semester_id
            WHERE c.id = ?
        """, (class_id,)).fetchone()

        # Finally, delete the class from database
        db.execute("DELETE FROM classes WHERE id = ?", (class_id,))
        db.commit()

        # ✅ Remove corresponding class folder
        if class_info:
            import shutil, os
            from app.models.classes import BASE_CLASS_FOLDER

            semester = class_info["semester"]
            class_name = class_info["class_name"]
            class_folder = os.path.join(BASE_CLASS_FOLDER, semester, class_name)

            if os.path.exists(class_folder):
                shutil.rmtree(class_folder, ignore_errors=True)
                print(f"🗑️ Deleted folder: {class_folder}")
            else:
                print(f"⚠️ Folder not found (nothing to delete): {class_folder}")

    except Exception as e:
        db.rollback()
        raise RuntimeError(f"Failed to delete class {class_id}: {e}")


# ----------------------------------------------------------------------------------
# FORM HELPERS
# ----------------------------------------------------------------------------------

def parse_class_form(form):
    semester_id = int(form['semester_id'])
    class_number = int(form['class_number'])
    instructor_id = int(form['instructor_id'])

    if class_number <= 0:
        raise ValueError("Class number must be positive.")
    if semester_id <= 0:
        raise ValueError("Semester ID must be positive.")
    if instructor_id <= 0:
        raise ValueError("Instructor ID must be positive.")

    return {
        'semester_id': semester_id,
        'code': form['code'],
        'class_number': class_number,
        'class_name': form['class_name'],
        'description': form.get('description', ''),
        'instructor_id': instructor_id
    }


def bulk_delete_from_form(form):
    class_ids = form.getlist('class_ids')
    if not class_ids:
        flash("No classes selected for deletion.", "warning")
        return False
    delete_classes(class_ids)
    flash("Selected classes deleted successfully!", "success")
    return True

# ----------------------------------------------------------------------------------
# DROPDOWN DATA
# ----------------------------------------------------------------------------------

def get_instructors_dropdown():
    db = get_db()
    return db.execute("""
        SELECT u.id, u.name
        FROM users u
        JOIN user_groups ug ON u.id = ug.user_id
        JOIN groups g ON ug.group_id = g.id
        WHERE g.name = 'Instructor'
        ORDER BY u.name
    """).fetchall()

def get_semesters_dropdown():
    db = get_db()
    return db.execute("""
        SELECT id, term, year, year || ' - ' || term AS label
        FROM semesters
        ORDER BY year DESC,
            CASE term WHEN 'Spring' THEN 1 WHEN 'Summer' THEN 2 WHEN 'Fall' THEN 3 END
    """).fetchall()

# ----------------------------------------------------------------------------------
# STUDENT MANAGEMENT HELPERS
# ----------------------------------------------------------------------------------
def add_students_to_class(class_id, student_ids):
    """Add students to a class using semester_id instead of semester (string)."""
    class_details = get_class_by_id(class_id)
    if not class_details:
        raise ValueError(f"Class {class_id} does not exist.")

    semester_id = class_details.get("semester_id")
    if semester_id is None:
        raise ValueError(f"Class {class_id} does not have a valid semester_id.")

    query = """
        INSERT OR IGNORE INTO class_enrollments (class_id, user_id, semester_id)
        VALUES (?, ?, ?)
    """

    conn = get_db()
    try:
        with conn:
            for student_id in student_ids:
                print("Running SQL insert with values:", (class_id, student_id, semester_id))
                cursor = conn.execute(query, (class_id, student_id, semester_id))                
                print("Rowcount after insert:", cursor.rowcount)

    except sqlite3.IntegrityError:
        print(f"âš ï¸ Some students were already enrolled in class {class_id}")
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"âŒ Error adding students to class {class_id}: {e}")
    
def add_students_to_class_and_assignments(class_id, student_ids):
    """Enroll students in a class AND create individual assignments for all
    existing assignments in that class."""
    class_details = get_class_by_id(class_id)
    if not class_details:
        raise ValueError(f"Class {class_id} does not exist.")

    semester_id = class_details.get("semester_id")
    if semester_id is None:
        raise ValueError(f"Class {class_id} does not have a valid semester_id.")

    conn = get_db()
    try:
        with conn:
            # Get all assignments for this class
            assignments = conn.execute("""
                SELECT id, name, start_date, completion_date, parent_step_id
                FROM assignments WHERE class_id = ?
            """, (class_id,)).fetchall()

            for student_id in student_ids:
                # Enroll in class (same as add_students_to_class)
                conn.execute("""
                    INSERT OR IGNORE INTO class_enrollments (class_id, user_id, semester_id)
                    VALUES (?, ?, ?)
                """, (class_id, student_id, semester_id))

                # Create individual assignment for each assignment
                for assignment in assignments:
                    assignment_id  = assignment["id"]
                    parent_step_id = assignment["parent_step_id"]

                    # Skip if already assigned
                    existing = conn.execute("""
                        SELECT 1 FROM individual_assignments
                        WHERE assignment_id = ? AND users_id = ?
                    """, (assignment_id, student_id)).fetchone()
                    if existing:
                        continue

                    # Insert individual assignment
                    conn.execute("""
                        INSERT INTO individual_assignments
                        (assignment_id, users_id, name, start_date, completion_date)
                        VALUES (?, ?, ?, ?, ?)
                    """, (assignment_id, student_id, assignment["name"],
                          assignment["start_date"], assignment["completion_date"]))

                    individual_assignment_id = conn.execute(
                        "SELECT last_insert_rowid()"
                    ).fetchone()[0]

                    # Get workflow steps
                    steps = conn.execute("""
                        SELECT id FROM steps WHERE parent_id = ?
                    """, (parent_step_id,)).fetchall()

                    # Create status record for each step
                    for step in steps:
                        top_node = conn.execute("""
                            SELECT name FROM nodes
                            WHERE step_id = ?
                            ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INTEGER)
                            LIMIT 1
                        """, (step["id"],)).fetchone()

                        if top_node:
                            conn.execute("""
                                INSERT OR IGNORE INTO individual_assignment_statuses
                                (individual_assignment_id, step_id, current_status)
                                VALUES (?, ?, ?)
                            """, (individual_assignment_id, step["id"], top_node["name"]))

        print(f"[OK] Enrolled {len(student_ids)} students with assignments in class {class_id}.")

    except sqlite3.IntegrityError:
        print(f"⚠️ Some students were already enrolled in class {class_id}")
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"❌ Error in add_students_to_class_and_assignments: {e}")

def remove_students_from_class_db(class_id, student_ids):
    """Remove students from a class and clean up related individual assignments and statuses."""
    conn = get_db()
    try:
        with conn:
            # ðŸ”¹ Step 1: Delete individual assignment statuses first
            conn.execute("""
                DELETE FROM individual_assignment_statuses 
                WHERE individual_assignment_id IN (
                    SELECT id FROM individual_assignments 
                    WHERE users_id IN ({}) AND assignment_id IN (
                        SELECT id FROM assignments WHERE class_id = ?
                    )
                )
            """.format(','.join('?' for _ in student_ids)), [*student_ids, class_id])

            # Step 1.5: step_locks has no FK to individual_assignments any
            # more (entity_id is polymorphic across assignment/shot_step/
            # scene_step -- see migrate_polymorphic_step_locks.py), so it no
            # longer cascades on its own and must be cleaned up manually
            # here too, same as individual_assignment_statuses above.
            conn.execute("""
                DELETE FROM step_locks
                WHERE entity_type = 'assignment' AND entity_id IN (
                    SELECT id FROM individual_assignments
                    WHERE users_id IN ({}) AND assignment_id IN (
                        SELECT id FROM assignments WHERE class_id = ?
                    )
                )
            """.format(','.join('?' for _ in student_ids)), [*student_ids, class_id])

            # ðŸ”¹ Step 2: Delete individual assignments
            conn.execute("""
                DELETE FROM individual_assignments
                WHERE users_id IN ({}) AND assignment_id IN (
                    SELECT id FROM assignments WHERE class_id = ?
                )
            """.format(','.join('?' for _ in student_ids)), [*student_ids, class_id])

            # ðŸ”¹ Step 3: Remove students from class_enrollments
            conn.execute("""
                DELETE FROM class_enrollments 
                WHERE class_id = ? AND user_id IN ({})
            """.format(','.join('?' for _ in student_ids)), [class_id, *student_ids])

        print(f"[OK] Successfully removed students {student_ids} from class {class_id} and cleaned up assignments.")
    except Exception as e:
        conn.rollback()
        print(f"âŒ Error removing students from class {class_id}: {e}")
        raise e

def filter_students_by_name(students, query):
    query = query.strip().lower()
    return [
        student for student in students
        if query in student["name"].lower() or query in student["email"].lower()
    ]

def get_students_by_class_with_enrollment_marked(class_id, semester=None):
    enrolled = User.get_enrolled(class_id, semester=semester)
    all_students = User.get_all()
    enrolled_ids = {s["id"] for s in enrolled}

    for student in all_students:
        student["in_class"] = student["id"] in enrolled_ids

    return all_students, enrolled

def validate_student_action_payload(json_data):
    action = json_data.get("action")
    student_ids = json_data.get("student_ids", [])
    errors = []

    if action not in {"add", "remove"}:
        errors.append("Invalid or missing action. Use 'add' or 'remove'.")
    if not student_ids:
        errors.append("No student IDs provided.")

    return action, student_ids, errors

# ----------------------------------------------------------------------------------
# UTILITIES
# ----------------------------------------------------------------------------------

def create_class_folder_if_missing(class_id):
    db = get_db()
    row = db.execute("""
        SELECT c.class_name, s.year || '-' || s.term AS semester
        FROM classes c
        JOIN semesters s ON s.id = c.semester_id
        WHERE c.id = ?
    """, (class_id,)).fetchone()

    if not row:
        return False

    semester = row['semester']
    class_name = row['class_name']
    path = os.path.join(BASE_CLASS_FOLDER, semester, class_name, "Assignments")


    os.makedirs(path, exist_ok=True)
    return path  # optional: return for logging/debugging

def copy_assignments_from_class(source_class_id, target_class_id):
    from app.models import add_assignment_to_db
    db = get_db()

    source_assignments = db.execute("""
        SELECT a.name, a.parent_step_id, a.max_points,
               GROUP_CONCAT(aps.step_id) AS step_ids
        FROM assignments a
        JOIN assignment_progress_steps aps ON aps.assignment_id = a.id
        WHERE a.class_id = ?
        GROUP BY a.id
    """, (source_class_id,)).fetchall()

    if not source_assignments:
        raise ValueError("No assignments found in source class.")

    for a in source_assignments:
        step_ids = [int(s) for s in a["step_ids"].split(",")]
        add_assignment_to_db({
            "class_id": target_class_id,
            "name": a["name"],
            "start_date": "",
            "completion_date": "",
            "parent_step_id": a["parent_step_id"],
            "progress_step_ids": step_ids,
            "assign_option": "none",
            "selected_students": []
        })

