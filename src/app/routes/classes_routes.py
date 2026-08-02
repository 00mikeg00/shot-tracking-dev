# classes_routes.py
import os, json
import csv
import zipfile
import tempfile
import shutil
import re
import html
import traceback
from io import BytesIO
from flask import Blueprint, render_template, request, redirect, flash, url_for, jsonify, session, current_app, send_file
from app.models import get_assignments_by_class
from app.models.classes import (
    query_classes, get_all_classes, get_all_classes_minimal, get_class_by_id, get_all_classes_dict, fetch_unique_class_names, serialize_classes_for_dropdown,
    validate_class_exists, validate_class_number, get_class_folder_path,
    delete_classes, delete_class_by_id, create_class_folder_if_missing,copy_assignments_from_class,
    parse_class_form, bulk_delete_from_form, get_instructors_dropdown, get_semesters_dropdown,
    filter_students_by_name, get_students_by_class_with_enrollment_marked, validate_student_action_payload, add_students_to_class, remove_students_from_class_db, add_students_to_class_and_assignments
)
from app.utils.utils import role_required
from app.database.db import get_db
from app.utils.auth_utils import login_required, instructor_required
from app.models.user_model import User



import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

logger.debug(f"Imported get_class_by_id: {get_class_by_id}")
logger.debug(f"Imported get_assignments_by_class: {get_assignments_by_class}")

classes_bp = Blueprint('classes', __name__)

RIGS_FOLDER = os.getenv("RIGS_ROOT", r"C:/Cincy/Rigs")
RIG_EXTS = (".mb", ".ma", ".fbx")

# ----------------------------------------------------------------------------------
# CLASSES
# ----------------------------------------------------------------------------------

@classes_bp.route('/view', methods=['GET'])
@role_required('classes', ['Instructor', 'Admin'])
def view_classes():
    classes = get_all_classes_dict()
    swal_data = session.pop('swal_data', None)  # ðŸ’¡ pops after one render
    return render_template('classes/classes.html', classes=classes, rig_list=[], swal_data=swal_data)

@classes_bp.route('/class_details/<int:class_id>', methods=['GET'])
@role_required('classes', ['Instructor', 'Admin'])
def view_class_details(class_id):
    class_details = validate_class_exists(class_id)
    if not class_details:
        return redirect(url_for('classes.view_classes'))

    assignments = get_assignments_by_class(class_id)
    return render_template(
        'classes/view_class_details.html',
        class_details=class_details,
        assignments=assignments
    )

@classes_bp.route('/add_class', methods=['GET', 'POST'])
@role_required('classes', ['Instructor', 'Admin'])
def add_class_route():
    conn = get_db()

    if request.method == 'POST':
        try:
            new_class_data = parse_class_form(request.form)

            conn.execute("""
                INSERT INTO classes (semester_id, code, class_number, class_name, description, instructor_id)
                VALUES (:semester_id, :code, :class_number, :class_name, :description, :instructor_id)
            """, new_class_data)
            conn.commit()

            # [OK] Get the new class_id after insert
            class_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # [OK] Create folder for the new class
            folder_path = create_class_folder_if_missing(class_id)
            if folder_path:
                pretty_path = html.escape(folder_path)
                flash(f"Class added successfully!", "success")

            else:
                flash("Class added, but folder creation failed.", "error")


            return redirect(url_for('classes.view_classes'))
        except Exception as e:
            print(f" Add class error: {e}")
            flash({'type': 'danger', 'message': f"Error adding class: {e}"})

    # [OK] For GET: render form
    instructors = get_instructors_dropdown()
    semesters = get_semesters_dropdown()

    form_fields = [
        {
            'name': 'semester_id',
            'options': [{'value': str(row['id']), 'label': row['label']} for row in semesters]
        },
        {
            'name': 'code',
            'options': [{'value': v, 'label': v} for v in ['GAA', 'FAA', 'DMC']]
        },
        {
            'name': 'instructor_id',
            'options': [{'value': str(i['id']), 'label': i['name']} for i in instructors]
        }
    ]

    return render_template('classes/add_class.html', form_fields=form_fields)

@classes_bp.route('/edit/<int:class_id>', methods=['GET', 'POST'])
@role_required('classes', ['Instructor', 'Admin'])
def edit_class(class_id):
    db = get_db()

    # ðŸ”¹ Step 1: Get current class info and semester details
    class_data = db.execute("""
        SELECT c.*, s.term, s.year
        FROM classes c
        JOIN semesters s ON c.semester_id = s.id
        WHERE c.id = ?
    """, (class_id,)).fetchone()

    if not class_data:
        flash("Class not found!", "danger")
        return redirect(url_for('classes.view_classes'))

    class_data = dict(class_data)

    instructors = get_instructors_dropdown()
    semesters = get_semesters_dropdown()

    # ðŸ”¹ Build semester label like "2025-Fall"
    old_semester_label = f"{class_data['year']}-{class_data['term']}".replace(" ", "_")
    old_path = get_class_folder_path(old_semester_label, class_data['class_name'])

    if request.method == 'POST':
        new_class_name = request.form['class_name']
        new_description = request.form.get('description', '')
        new_semester_id = int(request.form['semester_id'])
        new_instructor_id = int(request.form['instructor_id'])

        folder_changed = (new_class_name != class_data['class_name']) or (new_semester_id != class_data['semester_id'])
        confirm_folder_change = request.form.get('confirm_folder_change')

        if folder_changed and confirm_folder_change != 'yes':
            flash("Class name or semester changed. Please confirm folder update.", "warning")
            class_data.update({
                'class_name': new_class_name,
                'description': new_description,
                'semester_id': new_semester_id,
                'instructor_id': new_instructor_id
            })
            return render_template("classes/edit_class.html",
                                   class_data=class_data,
                                   instructors=instructors,
                                   semesters=semesters,
                                   prompt_confirm=True)

        try:
            #  Step 2: Update the class in DB
            db.execute("""
                UPDATE classes 
                SET class_name = ?, description = ?, semester_id = ?, instructor_id = ?
                WHERE id = ?
            """, (new_class_name, new_description, new_semester_id, new_instructor_id, class_id))
            db.commit()

            #  Step 3: Folder operations if confirmed
            if folder_changed and confirm_folder_change == 'yes':
                try:
                    # Build new semester label and paths
                    new_semester = db.execute("SELECT term, year FROM semesters WHERE id = ?", (new_semester_id,)).fetchone()
                    new_semester_label = f"{new_semester['year']}-{new_semester['term']}".replace(" ", "_")
                    new_path = get_class_folder_path(new_semester_label, new_class_name)

                    print(" OLD PATH:", old_path)
                    print(" NEW PATH:", new_path)

                    # Delete old class folder
                    if os.path.exists(old_path):
                        print(" Deleting old class folder...")
                        shutil.rmtree(old_path)

                    # Create new class folder and Assignments subfolder
                    print(" Creating new class folder and Assignments subfolder...")
                    os.makedirs(os.path.join(new_path, "Assignments"), exist_ok=True)

                except Exception as e:
                    print(" ERROR in folder operations:", e)
                    traceback.print_exc()
                    flash(f"Folder update failed: {e}", "danger")


            flash("Class updated successfully!", "success")
            return redirect(url_for('classes.view_classes'))

        except Exception as e:
            flash(f"Error updating class: {e}", "danger")

    return render_template("classes/edit_class.html",
                           class_data=class_data,
                           instructors=instructors,
                           semesters=semesters)

@classes_bp.route('/delete/<int:class_id>', methods=['POST'])
@role_required('classes', ['Instructor', 'Admin'])
def delete_class(class_id):
    """Deletes a class and its associated data."""
    try:
        delete_class_by_id(class_id)
        return jsonify({"success": True})
    except Exception as e:
        print(f"Delete error: {e}")
        return jsonify({"success": False, "message": str(e)})

@classes_bp.route('/bulk_delete', methods=['POST'])
@role_required('classes', ['Instructor', 'Admin'])
def bulk_delete_classes():
    try:
        if not bulk_delete_from_form(request.form):
            session['swal_data'] = {
                "icon": "warning",
                "title": "No Selection",
                "text": "No classes were selected for deletion."
            }
            return redirect(url_for('classes.view_classes'))
    except Exception as e:
        session['swal_data'] = {
            "icon": "error",
            "title": "Deletion Failed",
            "text": "Failed to delete classes."
        }
        return redirect(url_for('classes.view_classes'))

    session['swal_data'] = {
        "icon": "success",
        "title": "Classes Deleted",
        "text": "Selected classes were deleted successfully."
    }
    return redirect(url_for('classes.view_classes'))

@classes_bp.route('/get_all_classes', methods=['GET'], endpoint='get_all_classes_route')
@role_required('classes', ['Instructor', 'Admin'])
def get_all_classes_route():
    try:
        return jsonify(serialize_classes_for_dropdown())
    except Exception as e:
        print(f"Error fetching class data: {e}")
        return jsonify({"error": "Failed to fetch classes"}), 500

@classes_bp.route('/api/classes/names', methods=['GET'])
@role_required('classes', ['Instructor', 'Admin'])
def get_all_class_names():
    try:
        return jsonify(fetch_unique_class_names())
    except Exception as e:
        print(f"âŒ Failed to fetch class names: {e}")
        return jsonify({"error": "Failed to load class names"}), 500


@classes_bp.route("/api/classes/by-semester/<int:semester_id>")
def get_classes_by_semester(semester_id):
    db = get_db()

    rows = db.execute("""
        SELECT DISTINCT class_name
        FROM classes
        WHERE semester_id = ?
        ORDER BY class_name
    """, (semester_id,)).fetchall()

    names = [row['class_name'] for row in rows]
    return jsonify(names)

# ----------------------------------------------------------------------------------
# STUDENTS
# ----------------------------------------------------------------------------------

@classes_bp.route('/students/<int:class_id>', methods=['GET'], endpoint='view_students_in_class')
@role_required('classes', ['Instructor', 'Admin'])
def view_students_in_class(class_id):
    try:
        search_available = request.args.get('search_available', '').strip().lower()
        search_enrolled = request.args.get('search_enrolled', '').strip().lower()

        selected_class = validate_class_exists(class_id)
        if not selected_class:
            return redirect(url_for('classes.view_classes'))

        available_students = User.get_not_in_class(class_id)
        enrolled_students = User.get_enrolled(class_id)

        if search_available:
            available_students = filter_students_by_name(available_students, search_available)
        if search_enrolled:
            enrolled_students = filter_students_by_name(enrolled_students, search_enrolled)

        conn = get_db()
        all_classes = get_all_classes_minimal(conn)

        return render_template(
            'classes/add_students.html',
            selected_class=selected_class,
            available_students=available_students,
            enrolled_students=enrolled_students,
            all_classes=all_classes,
            class_id=class_id,
            active_page='students',
            search_available=search_available,
            search_enrolled=search_enrolled
        )
    except Exception as e:
        return render_template(
            'classes/add_students.html',
            selected_class=None,
            available_students=[],
            enrolled_students=[],
            all_classes=[],
            class_id=class_id,
            swal_data={
                "icon": "error",
                "title": "Load Failed",
                "text": f"Could not fetch students: {e}"
            }
        )

@classes_bp.route("/<int:class_id>/students", methods=["GET"])
@role_required('classes', ['Instructor', 'Admin'])
def get_class_students(class_id):
    try:
        filters = {'id': class_id}
        selected_class = query_classes(filters=filters)
        if not selected_class:
            flash({'type': 'error', 'message': 'Class not found.'})
            return redirect(url_for("classes.view_classes"))

        selected_class = selected_class[0]
        semester = selected_class["semester"]

        all_students, _ = get_students_by_class_with_enrollment_marked(class_id, semester)
        conn = get_db()
        classes = [dict(cls) for cls in get_all_classes_minimal(conn)]

        return render_template(
            "classes/class_students.html",
            classes=classes,
            selected_class=selected_class,
            students=all_students,
            class_id=class_id,
        )
    except Exception as e:
        return render_template(
            "classes/class_students.html",
            classes=[],
            selected_class=None,
            students=[],
            class_id=class_id,
            swal_data={
                "icon": "error",
                "title": "Error Fetching Students",
                "text": str(e)
            }
        )

@classes_bp.route('/students/<int:class_id>', methods=['POST'])
@role_required('classes', ['Instructor', 'Admin'])
def manage_students_in_class(class_id):
    try:
        data = request.json
        action, student_ids, errors = validate_student_action_payload(data)

        if errors:
            return jsonify({"success": False, "message": "; ".join(errors)}), 400

        if action == 'add':
            also_add_to_assignments = data.get("also_add_to_assignments", False)
            if also_add_to_assignments:
                add_students_to_class_and_assignments(class_id, student_ids)
                return jsonify({"success": True, "message": f"Added {len(student_ids)} student(s) to class and all assignments."})
            else:
                add_students_to_class(class_id, student_ids)
                return jsonify({"success": True, "message": f"Added {len(student_ids)} student(s) successfully."})
        elif action == 'remove':
            remove_students_from_class_db(class_id, student_ids)
            return jsonify({"success": True, "message": f"Removed {len(student_ids)} student(s) successfully."})
    except Exception as e:
        print(f"Error in managing students: {e}")
        return jsonify({"success": False, "message": f"Error managing students: {e}"}), 500

@classes_bp.route('/import_canvas_students/<int:class_id>', methods=['POST'])
@instructor_required
def import_canvas_students(class_id):
    import csv, io
    from werkzeug.security import generate_password_hash

    action = request.form.get('action', 'preview')
    file = request.files.get('csv_file')

    if not file:
        return jsonify({"error": "No file provided"}), 400

    stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
    reader = csv.DictReader(stream)

    DEFAULT_PASSWORD = generate_password_hash("00Cats00")
    STUDENT_GROUP_ID = 1

    students = []
    for row in reader:
        raw_name = row.get("Student", "").strip()
        login = row.get("SIS Login ID", "").strip()

        # Skip empty rows, Points Possible row, and Test Student
        if not raw_name or not login:
            continue
        if raw_name.lower() == "points possible":
            continue
        if "test" in raw_name.lower():
            students.append({"raw": raw_name, "login": login, "skip": True, "reason": "Test Student"})
            continue

        # Convert "Last, First" → "First Last"
        parts = raw_name.split(",")
        if len(parts) == 2:
            full_name = f"{parts[1].strip()} {parts[0].strip()}"
        else:
            full_name = raw_name

        students.append({
            "raw": raw_name,
            "name": full_name,
            "login": login,
            "skip": False
        })

    if not students:
        return jsonify({"error": "No valid students found in CSV"}), 400

    conn = get_db()

    # Check which students already exist
    results = []
    for s in students:
        if s.get("skip"):
            results.append({**s, "status": "skipped"})
            continue

        existing = conn.execute(
            "SELECT id, name FROM users WHERE login_name = ?", (s["login"],)
        ).fetchone()

        results.append({
            **s,
            "status": "exists" if existing else "new",
            "user_id": existing["id"] if existing else None
        })

    if action == "preview":
        return jsonify({"students": results, "class_id": class_id})

    # action == "import" — create missing users and enroll everyone
    enrolled = 0
    created = 0
    assigned = 0  # ← add this line

    also_add_to_assignments = request.form.get('also_add_to_assignments') == 'true'

    # Pre-fetch assignments once if needed
    class_assignments = []
    if also_add_to_assignments:
        class_assignments = conn.execute("""
            SELECT id, name, start_date, completion_date, parent_step_id
            FROM assignments
            WHERE class_id = ?
        """, (class_id,)).fetchall()

    class_row = conn.execute(
        "SELECT semester_id FROM classes WHERE id = ?", (class_id,)
    ).fetchone()
    semester_id = class_row["semester_id"] if class_row else None

    for s in results:
        if s["status"] == "skipped":
            continue

        user_id = s.get("user_id")

        if s["status"] == "new":
            # Create user
            cur = conn.execute("""
                INSERT INTO users (name, login_name, email, password_hash)
                VALUES (?, ?, ?, ?)
            """, (
                s["name"],
                s["login"],
                f"{s['login']}@mail.uc.edu",
                DEFAULT_PASSWORD
            ))
            user_id = cur.lastrowid

            # Assign Student group
            conn.execute("""
                INSERT OR IGNORE INTO user_groups (user_id, group_id)
                VALUES (?, ?)
            """, (user_id, STUDENT_GROUP_ID))

            created += 1

        # Enroll in class (skip if already enrolled)
        already_enrolled = conn.execute("""
            SELECT user_id FROM class_enrollments
            WHERE user_id = ? AND class_id = ?
        """, (user_id, class_id)).fetchone()

        if not already_enrolled:
            conn.execute("""
                INSERT INTO class_enrollments (user_id, class_id, semester_id)
                VALUES (?, ?, ?)
            """, (user_id, class_id, semester_id))
            enrolled += 1

        if also_add_to_assignments and class_assignments:
            for assignment in class_assignments:
                already_assigned = conn.execute("""
                    SELECT users_id FROM individual_assignments
                    WHERE assignment_id = ? AND users_id = ?
                """, (assignment["id"], user_id)).fetchone()

                if not already_assigned:
                    conn.execute("""
                        INSERT INTO individual_assignments
                        (assignment_id, users_id, name, start_date, completion_date)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        assignment["id"],
                        user_id,
                        assignment["name"],
                        assignment["start_date"],
                        assignment["completion_date"]
                    ))
                    ia_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                    steps = conn.execute("""
                        SELECT id FROM steps WHERE parent_id = ?
                    """, (assignment["parent_step_id"],)).fetchall()

                    for step in steps:
                        top_node = conn.execute("""
                            SELECT name FROM nodes
                            WHERE step_id = ?
                            ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INTEGER)
                            LIMIT 1
                        """, (step["id"],)).fetchone()

                        if top_node:
                            conn.execute("""
                                INSERT INTO individual_assignment_statuses
                                (individual_assignment_id, step_id, current_status)
                                VALUES (?, ?, ?)
                            """, (ia_id, step["id"], top_node["name"]))

                    assigned += 1

    conn.commit()

    return jsonify({
        "success": True,
        "created": created,
        "enrolled": enrolled,
        "assigned": assigned
    })

# ----------------------------------------------------------------------------------
# SEMESTERS
# ----------------------------------------------------------------------------------

@classes_bp.route('/check-semester', methods=['GET'])
@login_required
def check_semester():
    """AJAX endpoint to check if a semester exists"""
    year = request.args.get("year")
    semester = request.args.get("semester")

    if not year or not semester:
        return jsonify({"error": "Missing parameters"}), 400

    conn = get_db()
    query = "SELECT id FROM semesters WHERE year = ? AND term = ?"
    semester_exists = conn.execute(query, (year, semester)).fetchone()

    return jsonify({"exists": bool(semester_exists)})

@classes_bp.route('/semesters', methods=['GET'])
def get_semesters():
    """Return all semesters as JSON."""
    try:
        db = get_db()
        semesters = db.execute("""
            SELECT id, year, term
            FROM semesters
            ORDER BY year DESC,
                CASE term
                    WHEN 'Spring' THEN 1
                    WHEN 'Summer' THEN 2
                    WHEN 'Fall' THEN 3
                END
        """).fetchall()

        return jsonify([
            {"id": row["id"], "year": row["year"], "term": row["term"]}
            for row in semesters
        ])
    except Exception as e:
        print(f"âŒ Failed to fetch semesters: {e}")
        return jsonify({"error": "Failed to fetch semesters"}), 500

# ----------------------------------------------------------------------------------
# ASSIGNMENTS
# ----------------------------------------------------------------------------------

@classes_bp.route('/api/assignments/by-class/<class_name>', methods=['GET'])
@role_required('classes', ['Instructor', 'Admin'])
def get_assignments_for_class_name(class_name):
    db = get_db()
    try:
        rows = db.execute("""
            SELECT a.name
            FROM assignments a
            JOIN classes c ON a.class_id = c.id
            WHERE c.class_name = ?
            ORDER BY a.name
        """, (class_name,)).fetchall()

        assignment_names = sorted(set(row["name"] for row in rows))
        return jsonify(assignment_names)
    except Exception as e:
        print(f"âŒ Failed to fetch assignments for class '{class_name}': {e}")
        return jsonify([]), 500

@classes_bp.route('/api/assignment-config/save-to-disk', methods=['POST'])
@role_required('classes', ['Instructor', 'Admin'])
def save_assignment_config_to_disk():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data received."}), 400

        filepath = os.path.join("C:/Cincy/Configs", "assignments_config.json")
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    
@classes_bp.route('/api/assignment-config/save-draft', methods=['POST'])
@role_required('classes', ['Instructor', 'Admin'])
def save_draft_config():
    try:
        data = request.get_json()
        path = "C:/Cincy/Configs/_draft_assignments_config.json"

        with open(path, 'w', encoding='utf-8') as f:
            import json
            json.dump(data, f, indent=2)

        return jsonify({"success": True})
    except Exception as e:
        print(f"âŒ Draft save failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@classes_bp.route('/copy_assignments/<int:target_class_id>', methods=['POST'])
@role_required('classes', ['Instructor', 'Admin'])
def copy_assignments(target_class_id):
    try:
        source_class_id = request.form.get('source_class_id', type=int)
        if not source_class_id:
            return jsonify({"success": False, "message": "No source class selected."}), 400
        
        copy_assignments_from_class(source_class_id, target_class_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ----------------------------------------------------------------------------------
# RIGS
# ----------------------------------------------------------------------------------

@classes_bp.route('/api/rigs', methods=['GET'])
@login_required
def get_all_rigs():
    try:
        if not os.path.isdir(RIGS_FOLDER):
            current_app.logger.warning("RIGS folder missing: %s", RIGS_FOLDER)
            return jsonify([]), 200

        rig_files = []
        for root, _, files in os.walk(RIGS_FOLDER):
            for f in files:
                if f.lower().endswith(RIG_EXTS):
                    rig_files.append(os.path.join(root, f).replace("\\", "/"))

        rig_files.sort()
        current_app.logger.info("Rigs found: %d in %s", len(rig_files), RIGS_FOLDER)
        return jsonify(rig_files), 200
    except Exception:
        current_app.logger.exception("Failed to list rigs")
        return jsonify([]), 200

# ----------------------------------------------------------------------------------
# EXPORT CSV
# ----------------------------------------------------------------------------------

@classes_bp.route("/export_class/<int:class_id>", methods=["GET"])
@role_required('classes', ['Instructor', 'Admin'])
def export_class_zip(class_id):
    try:
        db = get_db()

        # -------------------------
        # Get class info
        # -------------------------
        class_row = db.execute("""
            SELECT c.class_name, s.year, s.term
            FROM classes c
            JOIN semesters s ON c.semester_id = s.id
            WHERE c.id = ?
        """, (class_id,)).fetchone()

        if not class_row:
            return jsonify({"error": "Class not found"}), 404

        class_name = class_row["class_name"]
        semester_label = f"{class_row['year']}-{class_row['term']}".replace(" ", "_")

        class_folder = get_class_folder_path(semester_label, class_name)
        print("CLASS FOLDER PATH:", class_folder)

        if not os.path.exists(class_folder):
            return jsonify({"error": "Class folder not found on disk"}), 404

        # -------------------------
        # Create ZIP in memory
        # -------------------------
        memory_file = BytesIO()

        with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(class_folder):
                for file in files:
                    file_path = os.path.join(root, file)

                    # Preserve folder structure relative to class folder
                    arcname = os.path.relpath(file_path, class_folder)

                    zf.write(file_path, arcname)

        memory_file.seek(0)

        safe_class_name = "".join(
            c if c.isalnum() or c in (" ", "_", "-") else "_"
            for c in class_name
        ).strip()

        zip_filename = f"{safe_class_name}.zip"

        return send_file(
            memory_file,
            mimetype="application/zip",
            as_attachment=True,
            download_name=zip_filename
        )

    except Exception as e:
        print("Export ZIP error:", e)
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500