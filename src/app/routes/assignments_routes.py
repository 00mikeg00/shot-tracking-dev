import os
import json
import glob
import re
import logging
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, flash, url_for, jsonify, current_app, session
from app.models.classes import (
    query_classes,
    get_all_classes
)
from app.models import (
    get_assignments_by_class, update_assignment, add_individual_assignment,
    add_assignment_to_db, delete_assignment_from_db
)
from app.models.assignment_model import get_individual_assignments_by_assignment, get_assignment_form_data
from app.database.db import get_db
from app.utils.auth_utils import login_required, instructor_required, get_user_permission_level
from app.utils.grade_utils import save_grade_history

import traceback
from dotenv import load_dotenv
load_dotenv()

assignments_bp = Blueprint(
    'assignments', __name__, template_folder='../../templates/assignments'
)

# ----------------------------------------------------------------------------------
# VIEWS: HTML Pages for Assignments
# ----------------------------------------------------------------------------------
@assignments_bp.route('/view_assignments/<int:class_id>', methods=['GET'])
@instructor_required 
def view_assignments(class_id):
    """Render the assignments page for a class, even if no assignments exist."""
    try:
        user_id = session.get('user_id')
        conn = get_db()

        assignments = get_assignments_by_class(class_id, conn) or []
        assignment_id = assignments[0]['id'] if assignments else None

        if not assignments:
            alert = {"type": "warning", "message": "No assignments found for this class."}
        all_classes = get_all_classes()
        assignment_steps = {
            assignment['id']: [
                {"id": row["id"], "name": row["name"]}
                for row in conn.execute("""
                    SELECT s.id, s.name
                    FROM assignment_progress_steps aps
                    JOIN steps s ON aps.step_id = s.id
                    WHERE aps.assignment_id = ?
                    ORDER BY s.order_num ASC
                """, (assignment['id'],)).fetchall()
            ]
            for assignment in assignments
        }
        
        # Count students in this class
        student_count_row = conn.execute("""
            SELECT COUNT(*) AS count
            FROM class_enrollments ce
            JOIN users u ON ce.user_id = u.id
            WHERE ce.class_id = ?
        """, (class_id,)).fetchone()

        student_count = student_count_row["count"] if student_count_row else 0


        return render_template(
            'assignments/view_assignments.html',
            assignment_id=assignment_id,
            assignments=assignments,
            class_id=class_id,
            all_classes=all_classes,
            active_page="assignments",
            assignment_steps=assignment_steps,
            student_count=student_count 
        )

    except Exception as e:
        flash(f"Error loading assignments: {e}", "danger")
        return redirect(url_for('classes.view_classes'))

@assignments_bp.route('/<int:assignment_id>/individual')
@login_required
def view_individual_assignments(assignment_id):
    try:
        user_id = session.get('user_id')
        class_id = request.args.get('class_id', type=int)

        if not class_id:
            alert = {"type": "error", "message": "Class ID is required."}
            return redirect(url_for('classes.view_classes'))

        db = get_db()

        assignments = db.execute("""
            SELECT id, name 
            FROM assignments 
            WHERE class_id = ?
            ORDER BY name
        """, (class_id,)).fetchall()
        assignments = [dict(row) for row in assignments]

        individual_assignments = get_individual_assignments_by_assignment(assignment_id, db)

        class_name = db.execute("SELECT class_name FROM classes WHERE id = ?", (class_id,)).fetchone()["class_name"]


        return render_template(
            'assignments/individual_assignments_view.html',
            assignments=assignments,
            class_id=class_id,
            assignment_id=assignment_id,
            user_id=user_id,
            individual_assignments=individual_assignments,
            class_name=class_name
        )

    except Exception as e:
        alert = {"type": "error", "message": f"An error occurred: {e}"}
        return redirect(url_for('assignments.view_assignments', class_id=class_id))

@assignments_bp.route('/assignments/add', methods=['GET', 'POST'])
def add_assignment():
    if request.method == 'GET':
        class_id = request.args.get("class_id")
        context = get_assignment_form_data(class_id)
        return render_template("assignments/add_assignment.html", **context)

    # POST logic
    data = request.form
    class_id = data.get('class_id')
    name = data.get('assignment_name')
    start_date = data.get('start_date')
    completion_date = data.get('completion_date')
    parent_step_id = data.get('parent_step_id')
    progress_step_ids = request.form.getlist("progress_step_ids")
    assign_option = data.get('assign_option', 'all')
    selected_students = request.form.getlist("selected_students")
    frame_start = data.get('frame_start') or None
    frame_end = data.get('frame_end') or None

    if not all([class_id, name, start_date, completion_date, parent_step_id, progress_step_ids]):
        context = get_assignment_form_data(class_id)
        context["alert"] = {"type": "error", "message": "All fields are required."}
        return render_template("assignments/add_assignment.html", **context)

    try:
        assignment_id = add_assignment_to_db({
            "class_id": class_id,
            "name": name,
            "start_date": start_date,
            "completion_date": completion_date,
            "parent_step_id": parent_step_id,
            "progress_step_ids": progress_step_ids,
            "assign_option": assign_option,
            "selected_students": selected_students,
            "frame_start": frame_start,
            "frame_end": frame_end
        })
        return redirect(url_for("assignments.view_assignments", class_id=class_id, success=True))

    except Exception as e:
        context = get_assignment_form_data(class_id)
        context["alert"] = {"type": "error", "message": f"Failed to create assignment: {e}"}
        return render_template("assignments/add_assignment.html", **context)

# ----------------------------------------------------------------------------------
# API: GET - Read-Only Assignment Data
# ----------------------------------------------------------------------------------

@assignments_bp.route('/api/assignment-progress-steps', methods=['GET'])
@login_required
def api_assignment_progress_steps():
    """
    Return the list of selected progress steps for a given assignment,
    as stored in the assignment_progress_steps join table.
    Shape: [{"step_id": 5}, {"step_id": 93}, ...] ordered by steps.order_num.
    """
    assignment_id = request.args.get("assignment_id", type=int)
    if not assignment_id:
        return jsonify([]), 200

    db = get_db()
    rows = db.execute("""
        SELECT aps.step_id
        FROM assignment_progress_steps aps
        JOIN steps s ON s.id = aps.step_id          -- ensures step exists + gives us order
        WHERE aps.assignment_id = ?
        ORDER BY s.order_num ASC
    """, (assignment_id,)).fetchall()

    return jsonify([{"step_id": r["step_id"]} for r in rows])


@assignments_bp.route('/api/view_assignments/<int:class_id>', methods=['GET'])
@login_required
def api_view_assignments(class_id):

    db = get_db()
    query = """
        SELECT id, name, start_date, completion_date, progress_step_id, parent_step_id, frame_start, frame_end
        FROM assignments
        WHERE class_id = ?
    """
    assignments = [dict(row) for row in db.execute(query, (class_id,))]

    return jsonify(assignments)

@assignments_bp.route('/api/get_individual_assignment_id', methods=['GET'])
def get_individual_assignment_id_api():
    user_id = request.args.get('user_id', type=int)
    class_id = request.args.get('class_id', type=int)
    assignment_name = request.args.get('assignment_name', '')

    if not user_id or not class_id or not assignment_name:
        return jsonify({"error": "Missing parameters"}), 400

    conn = get_db()
    rows = conn.execute("""
        SELECT ia.id, a.name as assignment_name
        FROM individual_assignments ia
        JOIN assignments a ON a.id = ia.assignment_id
        WHERE ia.users_id = ? AND a.class_id = ?
    """, (user_id, class_id)).fetchall()

    normalized = assignment_name.replace(" ", "").lower()
    for row in rows:
        if row["assignment_name"].replace(" ", "").lower() == normalized:
            return jsonify({"individual_assignment_id": row["id"]})

    return jsonify({"error": "Assignment not found"}), 404

@assignments_bp.route('/api/individual_assignments', methods=['GET'])
def api_individual_assignments():
    """API to fetch individual assignments grouped by student, with user_name included."""
    assignment_id = request.args.get("assignment_id")
    user_id = request.args.get("user_id")

    if not assignment_id or not user_id:
        return jsonify({"error": "Missing required parameters"}), 400

    cursor = get_db().cursor()

    # 🔹 Fetch all individual assignments and include user_name explicitly
    cursor.execute("""
        SELECT ia.id, ia.start_date, ia.completion_date, 
               ia.video_status, 
               u.name AS user_name,   -- ✅ always return username
               JSON_GROUP_ARRAY(
                   JSON_OBJECT(
                       'current_status', ias.current_status,
                       'step_id', ias.step_id,
                       'step_name', s.name
                   )
               ) AS statuses,
               s.name AS step_name
        FROM individual_assignments ia
        LEFT JOIN users u ON ia.users_id = u.id  
        LEFT JOIN individual_assignment_statuses ias ON ias.individual_assignment_id = ia.id
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN steps s ON s.id = ias.step_id
        WHERE ia.assignment_id = ?
        GROUP BY ia.id, user_name, ia.users_id;
    """, (assignment_id,))

    individual_assignments = []
    for row in cursor.fetchall():
        row_dict = dict(row)

        # ✅ make sure user_name is passed through cleanly
        row_dict["user_name"] = row["user_name"]

        # Convert JSON array to Python list
        raw_statuses = json.loads(row_dict["statuses"])
        deduped = {}
        for status in raw_statuses:
            deduped[status["step_id"]] = status
        row_dict["statuses"] = list(deduped.values())

        individual_assignments.append(row_dict)

    # Fetch available statuses for each step
    cursor.execute("""
        SELECT DISTINCT 
            s.id AS parent_step_id, 
            c.id AS child_step_id, 
            c.name AS step_name, 
            n.name AS status_name, 
            CAST(SUBSTR(n.position, INSTR(n.position, ' ') + 1) AS INTEGER) AS y_position, 
            n.color AS status_color
        FROM steps s
        LEFT JOIN steps c ON c.parent_id = s.id  
        LEFT JOIN nodes n ON n.step_id = c.id  
        WHERE s.id IN (
            SELECT DISTINCT a.parent_step_id
            FROM assignments a
            WHERE a.id = ?
        )
        ORDER BY c.id, y_position ASC;
    """, (assignment_id,))

    available_statuses = cursor.fetchall()
    status_options = {}
    for row in available_statuses:
        step_id = row["child_step_id"] if row["child_step_id"] else None
        status_name = row["status_name"] if row["status_name"] else "Unknown Status"
        status_color = row["status_color"] if row["status_color"] else "#FFFFFF"
        if step_id not in status_options:
            status_options[step_id] = []
        status_options[step_id].append({"name": status_name, "color": status_color})

    return jsonify({
        "assignments": individual_assignments,
        "status_options": status_options
    })


@assignments_bp.route('/api/unassigned_students', methods=['GET'])
@login_required
def get_unassigned_students():
    """Fetch students in the class who are NOT assigned to the given assignment."""
    class_id = request.args.get('class_id', type=int)
    assignment_id = request.args.get('assignment_id', type=int)

    if not class_id or not assignment_id:
        return jsonify({"success": False, "error": "Missing class_id or assignment_id"}), 400

    db = get_db()

    # [OK] Query: Get students enrolled in the class but not assigned to the assignment
    query = """
        SELECT users.id, users.name 
        FROM users
        JOIN class_enrollments ON users.id = class_enrollments.user_id
        WHERE class_enrollments.class_id = ?
        AND users.id NOT IN (
            SELECT users_id FROM individual_assignments WHERE assignment_id = ?
        )
    """

    unassigned_students = [dict(row) for row in db.execute(query, (class_id, assignment_id))]
    
    return jsonify({"success": True, "unassigned_students": unassigned_students})

@assignments_bp.route("/api/steps-for-assignment")
def get_steps_for_assignment():
    try:
        assignment_id = request.args.get("assignment_id", type=int)
        if not assignment_id:
            return jsonify([])

        conn = get_db()

        parent = conn.execute(
            "SELECT parent_step_id FROM assignments WHERE id = ?",
            (assignment_id,)
        ).fetchone()

        if not parent or not parent["parent_step_id"]:
            return jsonify([])

        steps = conn.execute(
            """
            SELECT id, name, order_num
            FROM steps
            WHERE parent_id = ?
            ORDER BY order_num
            """,
            (parent["parent_step_id"],)
        ).fetchall()

        return jsonify([dict(s) for s in steps])

    except Exception:
        return jsonify([]), 500

@assignments_bp.route("/api/all-steps")
@login_required
def get_all_steps_api():
    conn = get_db()
    rows = conn.execute("SELECT id, name, order_num FROM steps ORDER BY order_num").fetchall()
    return jsonify([{"id": r["id"], "name": r["name"], "order_num": r["order_num"]} for r in rows])

@assignments_bp.route("/api/steps-for-assignments", methods=["POST"])
def get_steps_for_multiple_assignments():
    try:
        data = request.get_json()
        assignment_ids = data.get("assignment_ids", [])

        if not assignment_ids:
            return jsonify({"steps": [], "status_options": {}})

        conn = get_db()
        placeholders = ",".join("?" for _ in assignment_ids)

        steps_query = f"""
            SELECT DISTINCT s.id, s.name, s.order_num
            FROM individual_assignments ia
            JOIN assignments a ON ia.assignment_id = a.id
            JOIN steps s ON s.parent_id = a.parent_step_id
            WHERE ia.id IN ({placeholders})
            ORDER BY s.order_num
        """
        steps = conn.execute(steps_query, assignment_ids).fetchall()
        step_list = [dict(row) for row in steps]
        step_ids = [row["id"] for row in steps]

        if not step_ids:
            return jsonify({"steps": step_list, "status_options": {}})

        placeholders_steps = ",".join("?" for _ in step_ids)
        status_query = f"""
            SELECT 
                s.id AS step_id,
                n.name AS status_name,
                n.color AS status_color,
                CAST(SUBSTR(n.position, INSTR(n.position, ' ') + 1) AS INTEGER) AS y_position
            FROM steps s
            JOIN nodes n ON s.id = n.step_id
            WHERE s.id IN ({placeholders_steps})
            ORDER BY s.id, y_position
        """
        status_rows = conn.execute(status_query, step_ids).fetchall()

        status_options = {}
        for row in status_rows:
            sid = row["step_id"]
            status_options.setdefault(sid, []).append({
                "name": row["status_name"],
                "color": row["status_color"],
                "y_position": row["y_position"]
            })

        return jsonify({
            "steps": step_list,
            "status_options": status_options
        })

    except Exception:
        return jsonify({"error": "Internal server error"}), 500

@assignments_bp.route('/assignments/<int:assignment_id>/workflow', methods=['GET'])
def get_workflow_data(assignment_id):
    try:
        db = get_db()
        query = """
            SELECT t.id, t.name, n.id as node_id, n.name as node_name, n.color,
                   ias.current_status
            FROM steps t
            JOIN nodes n ON t.id = n.step_id
            LEFT JOIN individual_assignment_statuses ias 
                ON t.id = ias.step_id 
                AND ias.individual_assignment_id = (
                    SELECT id FROM individual_assignments 
                    WHERE assignment_id = ? LIMIT 1
                )
            WHERE t.parent_id IS NOT NULL
            ORDER BY t.id, n.id
        """
        result = db.execute(query, (assignment_id,)).fetchall()

        workflow_data = {}
        for row in result:
            step_name = row["name"]
            if step_name not in workflow_data:
                workflow_data[step_name] = {
                    "nodes": [],
                    "current": row["current_status"] or ""
                }

            workflow_data[step_name]["nodes"].append({
                "id": row["node_id"],
                "name": row["node_name"],
                "color": row["color"]
            })

        return jsonify(workflow_data)

    except Exception:
        return jsonify({"error": "Failed to load workflow data."}), 500

@assignments_bp.route('/api/entire_workflow', methods=['GET'])
def get_entire_workflow():
    try:
        assignment_id = request.args.get('assignment_id', type=int)
        if not assignment_id:
            return jsonify({"error": "Missing assignment_id"}), 400

        db = get_db()

        workflow_result = db.execute(
            "SELECT workflow_id FROM assignments WHERE id = ?",
            (assignment_id,)
        ).fetchone()

        workflow_id = workflow_result["workflow_id"] if workflow_result else None
        if not workflow_id:
            return jsonify({"error": "Workflow not found"}), 404

        query = """
            SELECT DISTINCT
                t.id, t.name,
                n.id as node_id, n.name as node_name, n.color, n.position,
                ias.current_status AS current_status
            FROM steps t
            JOIN nodes n ON t.id = n.step_id
            LEFT JOIN (
                SELECT step_id, current_status 
                FROM individual_assignment_statuses 
                WHERE individual_assignment_id IN (
                    SELECT id FROM individual_assignments WHERE assignment_id = ?
                )
                GROUP BY step_id
            ) ias ON t.id = ias.step_id
            WHERE t.parent_id IS NOT NULL
            AND t.workflow_id = ?
            ORDER BY t.id, n.id
        """

        results = db.execute(query, (assignment_id, workflow_id)).fetchall()
        return jsonify([dict(row) for row in results])

    except Exception:
        return jsonify({"error": "Failed to load entire workflow"}), 500

@assignments_bp.route('/check_cross_flows', methods=['GET'])
def check_cross_flows():
    """Return available cross-flows for a given step/status."""
    try:
        step_name = request.args.get('step_name')
        status = request.args.get('status')

        if not step_name or not status:
            return jsonify({"error": "Missing step_name or status"}), 400

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                t.name AS target_flow,
                n.name AS target_status,
                n.color AS target_color
            FROM links l
            JOIN steps t ON l.to_flow_id = t.id
            JOIN nodes n ON l.child_node_id = n.id
            WHERE l.parent_node_id IN (
                SELECT id FROM nodes 
                WHERE step_id = (SELECT id FROM steps WHERE name = ?)
                  AND name = ?
            )
        """, (step_name, status))

        cross_flows = [dict(row) for row in cursor.fetchall()]
        return jsonify({"cross_flows": cross_flows})

    except Exception:
        return jsonify({"error": "Failed to retrieve cross-flows"}), 500

@assignments_bp.route('/api/status_summary/<int:class_id>', methods=['GET'])
@login_required
def status_summary(class_id):
    """API to return progress status summary for assignments."""
    assignment_id = request.args.get("assignment_id", type=int)
    progress_step_id = request.args.get("progress_step_id", type=int)

    if not assignment_id:
        return jsonify({"error": "Missing assignment_id"}), 400

    if progress_step_id is None:
        # Try to automatically infer it for single-step assignments
        db = get_db()
        row = db.execute("""
            SELECT progress_step_id 
            FROM assignments 
            WHERE id = ?
        """, (assignment_id,)).fetchone()
        if not row or not row["progress_step_id"]:
            return jsonify({"error": "Missing progress_step_id"}), 400
        progress_step_id = row["progress_step_id"]


    try:
        db = get_db()
        query = """
            SELECT 
                ias.current_status AS status, 
                COUNT(DISTINCT ias.individual_assignment_id) AS count, 
                MAX(n.color) AS color
            FROM individual_assignment_statuses AS ias
            JOIN nodes AS n 
              ON ias.current_status = n.name 
             AND ias.step_id = n.step_id
            WHERE ias.step_id = ?
              AND ias.individual_assignment_id IN (
                  SELECT DISTINCT id FROM individual_assignments WHERE assignment_id = ?
              )
            GROUP BY ias.current_status
        """
        results = db.execute(query, (progress_step_id, assignment_id)).fetchall()

        data = [{ 
            "status": row["status"], 
            "count": row["count"], 
            "color": row["color"] or "#cccccc"
        } for row in results]

        return jsonify(data)

    except Exception:
        return jsonify({"error": "Failed to load status summary"}), 500


# ----------------------------------------------------------------------------------
# API: POST/PUT/DELETE - Modify Assignment Data
# ----------------------------------------------------------------------------------

@assignments_bp.route('/assignments/<int:assignment_id>/add', methods=['POST'])
def add_individual_assignment_route(assignment_id):
    """Assign a student to an existing assignment."""
    try:
        data = request.get_json()  # [OK] Expecting JSON data
        class_id = data.get("class_id")
        user_id = data.get("user_id")
        start_date = data.get("start_date")
        completion_date = data.get("completion_date")


        if not all([class_id, user_id, start_date, completion_date]):
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        # [OK] Fetch the assignment name
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name, frame_start, frame_end FROM assignments WHERE id = ?", (assignment_id,))
        assignment_name_row = cursor.fetchone()

        if not assignment_name_row:
            return jsonify({"success": False, "error": "Assignment not found"}), 404

        assignment_name = assignment_name_row["name"]  # [OK] Extract name

        # [OK] Call `add_individual_assignment` for this student
        add_individual_assignment(
            assignment_id=assignment_id,
            users_id=user_id,
            assignment_name=assignment_name,  # [OK] Ensure we include assignment name
            start_date=start_date,
            completion_date=completion_date,
            # current_status="Not Started",  # [OK] Default status
            frame_start=assignment_name_row["frame_start"],
            frame_end=assignment_name_row["frame_end"]
        )

        return jsonify({"success": True, "message": "Student added successfully!"})

    except Exception as e:
        print(f"âŒ ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@assignments_bp.route('/api/add_student', methods=['POST'])
@login_required
def add_student_to_assignment():
    """Assign a student to an assignment."""
    try:
        data = request.get_json()
        print("Received Data:", data)  # Debugging log

        assignment_id = data.get('assignment_id')
        student_id = data.get('student_id')

        if not assignment_id or not student_id:
            return jsonify({"success": False, "error": "Missing assignment_id or student_id"}), 400

        db = get_db()

        # [OK] Check if student is already assigned
        existing_assignment = db.execute(
            "SELECT id FROM individual_assignments WHERE assignment_id = ? AND users_id = ?",
            (assignment_id, student_id)
        ).fetchone()

        if existing_assignment:
            return jsonify({"success": False, "error": "Student is already assigned"}), 400

        # [OK] Fetch required fields from `assignments` table
        assignment = db.execute(
            "SELECT name, start_date, completion_date, frame_start, frame_end FROM assignments WHERE id = ?", (assignment_id,)
        ).fetchone()

        if not assignment:
            return jsonify({"success": False, "error": "Assignment not found"}), 404

        assignment_name = assignment['name']
        start_date = assignment['start_date']
        completion_date = assignment['completion_date']

        # [OK] Insert into `individual_assignments`
        # ðŸ‘‡ Replace your manual insert with this call
        current_status = "Not Started"

        individual_assignment_id = add_individual_assignment(
            assignment_id=assignment_id,
            users_id=student_id,
            assignment_name=assignment_name,
            start_date=start_date,
            completion_date=completion_date,
            current_status=current_status,  # [OK] Fix applied here
            frame_start=assignment['frame_start'],
            frame_end=assignment['frame_end']
        )

        # [OK] Fetch step IDs for the assignment's parent_step_id
        step_ids = db.execute("""
            SELECT id FROM steps WHERE parent_id = (
                SELECT parent_step_id FROM assignments WHERE id = ?
            )
        """, (assignment_id,)).fetchall()


        return jsonify({"success": True, "message": "Student added successfully."})

    except Exception as e:
        print("âŒ Error adding student:", traceback.format_exc())  # Full error log
        return jsonify({"success": False, "error": str(e)}), 500

@assignments_bp.route('/assignments/<int:assignment_id>/edit', methods=['POST'])
def edit_assignment(assignment_id):
    """Edit an assignment."""
    try:
        
        # Ensure JSON is correctly received
        data = request.get_json()
        if not data:
            print("âŒ ERROR: No JSON data received!")
            return jsonify({"success": False, "error": "Invalid JSON received"}), 400

        name = data.get("name")
        start_date = data.get("start_date")
        completion_date = data.get("completion_date")
        frame_start = data.get("frame_start") or None
        frame_end = data.get("frame_end") or None

        # Validate fields
        if not all([name, start_date, completion_date]):
            print(f"âŒ ERROR: Missing required fields in {data}")
            return jsonify({"success": False, "error": "Missing required fields"}), 400

        # Call function to update the database
        update_assignment(assignment_id, name, start_date, completion_date, frame_start, frame_end)

        print(f"[OK] Assignment {assignment_id} updated successfully!")
        return jsonify({"success": True, "message": "Assignment updated successfully!"})

    except Exception as e:
        print(f"âŒ ERROR in edit_assignment: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@assignments_bp.route('/assignments/<int:assignment_id>/delete', methods=['POST'])
def delete_assignment(assignment_id):
    try:
        delete_assignment_from_db(assignment_id)
        return jsonify({"success": True, "message": "Assignment deleted successfully"}), 200
    except Exception as e:
        print(f"Error deleting assignment {assignment_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

def update_assignment_status_and_crossflow(conn, individual_assignment_id, step_id, new_status):
    """
    Sets current_status for (individual_assignment_id, step_id) and propagates
    any crossflow links to their target steps on the same individual
    assignment. Shared by the authenticated dashboard route and the
    unauthenticated launcher route (playblast tooling running from Maya,
    no browser session available) so there's exactly one implementation of
    this logic instead of two that can drift apart.

    Returns (success: bool, payload: dict) — payload is either
    {"updated_steps": [...]} or {"error": "..."}.
    """
    cursor = conn.cursor()

    save_grade_history(conn, individual_assignment_id, step_id, new_status)

    cursor.execute("""
        INSERT OR REPLACE INTO individual_assignment_statuses (individual_assignment_id, step_id, current_status)
        VALUES (?, ?, ?)
    """, (individual_assignment_id, step_id, new_status))
    conn.commit()

    cursor.execute(
        "SELECT id FROM nodes WHERE name = ? AND step_id = ?",
        (new_status, step_id)
    )
    parent_node_row = cursor.fetchone()
    if not parent_node_row:
        logging.error(f"❌ Node ID not found for status '{new_status}' and step_id '{step_id}'")
        return False, {"error": f"Node ID not found for status '{new_status}' and step_id '{step_id}'"}

    parent_node_id = parent_node_row[0]

    cursor.execute("""
        SELECT to_flow_id, child_node_id
        FROM links
        WHERE parent_node_id = ? AND step_id = ?
    """, (parent_node_id, step_id))
    crossflow_links = cursor.fetchall()

    updated_steps = []

    for link in crossflow_links:
        to_flow_id = link[0]
        child_node_id = link[1]

        cursor.execute(
            "SELECT name FROM nodes WHERE id = ? AND step_id = ?",
            (child_node_id, to_flow_id)
        )
        node_name_row = cursor.fetchone()
        if not node_name_row:
            logging.error(f"❌ Node name not found for child_node_id '{child_node_id}' and to_flow_id '{to_flow_id}'")
            continue

        child_node_name = node_name_row[0]
        target_individual_id = individual_assignment_id

        cursor.execute("""
            INSERT OR REPLACE INTO individual_assignment_statuses (individual_assignment_id, step_id, current_status)
            VALUES (?, ?, ?)
        """, (target_individual_id, to_flow_id, child_node_name))
        updated_steps.append({
            "target_individual_id": target_individual_id,
            "step_id": to_flow_id,
            "child_status": child_node_name
        })

    conn.commit()
    return True, {"updated_steps": updated_steps}


@assignments_bp.route('/api/update-status', methods=['POST'])
@login_required
def update_assignment_status():
    data = request.json
    individual_assignment_id = data.get("individual_assignment_id")
    step_id = data.get("step_id")
    new_status = data.get("current_status")

    if not individual_assignment_id or not step_id or not new_status:
        logging.error("❌ Error: Missing required parameters (individual_assignment_id, step_id, current_status)")
        return jsonify({"error": "Missing required parameters"}), 400

    try:
        conn = get_db()
        success, payload = update_assignment_status_and_crossflow(conn, individual_assignment_id, step_id, new_status)
        if not success:
            return jsonify(payload), 400

        logging.info(f"[OK] Status updated successfully for IA {individual_assignment_id}, Step {step_id}")
        return jsonify({"success": True, "message": "Status updated successfully", **payload})

    except Exception as e:
        logging.error(f"❌ Error updating status: {e}")
        return jsonify({"error": str(e)}), 500


@assignments_bp.route("/api/bulk-update", methods=["POST"])
@login_required
def bulk_update_assignments():
    try:
        data = request.get_json()
        ids = data.get("assignment_ids", [])
        updates = data.get("updates", {})

        if not ids or not updates:
            return jsonify({"error": "Missing required fields"}), 400

        conn = get_db()
        cursor = conn.cursor()

        for assignment_id in ids:
            for step_id, new_status in updates.items():
                cursor.execute("""
                    UPDATE individual_assignment_statuses
                    SET current_status = ?
                    WHERE individual_assignment_id = ? AND step_id = ?
                """, (new_status, assignment_id, step_id))

        conn.commit()
        return jsonify({"message": "Status updated", "count": len(ids)})

    except Exception as e:
        print("âŒ bulk_update_assignments error:", e)
        return jsonify({"error": "Internal server error"}), 500

# ----------------------------------------------------------------------------------
# API: Miscellaneous / Utility
# ----------------------------------------------------------------------------------

@assignments_bp.route("/api/step-id", methods=["POST"])
@login_required
def get_step_ids_for_assignments():
    try:
        data = request.get_json()
        assignment_ids = data.get("assignment_ids", [])

        if not assignment_ids:
            return jsonify({"error": "No assignment IDs provided"}), 400

        conn = get_db()
        query = """
            SELECT ia.id AS assignment_id, s.id AS step_id
            FROM individual_assignments ia
            JOIN assignments a ON ia.assignment_id = a.id
            JOIN steps s ON s.parent_id = a.parent_step_id
            WHERE s.name LIKE '%Assignment%'
              AND ia.id IN (%s)
        """ % ",".join("?" * len(assignment_ids))

        rows = conn.execute(query, assignment_ids).fetchall()
        result = {row["assignment_id"]: row["step_id"] for row in rows}
        return jsonify(result)

    except Exception as e:
        print("âŒ get_step_ids_for_assignments error:", e)
        return jsonify({"error": "Internal server error"}), 500

@assignments_bp.route("/todo", methods=["GET"])
def todo_page():
    user_id = session.get("user_id")

    if not user_id:
        return "Unauthorized", 401  # User must be logged in

    db = get_db()
    assignments = db.execute(
        "SELECT id, title, due_date FROM assignments WHERE user_id = ?", (user_id,)
    ).fetchall()

    return render_template("todo.html", assignments=assignments)

# ----------------------------------------------------------------------------------------------------------------------
# VIDEO FILES
# ----------------------------------------------------------------------------------------------------------------------

@assignments_bp.route('/check_existing_file/<int:individual_assignment_id>', methods=['GET'])
def check_existing_file(individual_assignment_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT file_path FROM individual_assignments WHERE id = ?", 
            (individual_assignment_id,)
        )
        result = cursor.fetchone()
        
        has_file = bool(result and result['file_path'] and os.path.exists(result['file_path']))
        
        return jsonify({
            'hasFile': has_file
        })
    except Exception as e:
        print(f"Error checking existing file: {e}")
        return jsonify({'error': str(e)}), 500

@assignments_bp.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        individual_assignment_id = request.form.get('individual_assignment_id')

        if not file or not file.filename:
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if not individual_assignment_id:
            return jsonify({'success': False, 'error': 'No assignment ID provided'}), 400

        # Check file extension
        extension = os.path.splitext(file.filename)[1].lower()
        if extension not in {'.avi', '.mov', '.webm'}:
            return jsonify({'success': False, 'error': 'Invalid file type'}), 400

        # Create upload directory if it doesn't exist
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'assignments', str(individual_assignment_id))
        os.makedirs(upload_dir, exist_ok=True)

        # Check for existing file and remove it
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT file_path FROM individual_assignments WHERE id = ?", 
            (individual_assignment_id,)
        )
        existing = cursor.fetchone()
        if existing and existing['file_path'] and os.path.exists(existing['file_path']):
            os.remove(existing['file_path'])

        # Save new file
        filename = secure_filename(file.filename)
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)

        # Update database - set status to 'converting' initially
        cursor.execute("""
            UPDATE individual_assignments 
            SET file_path = ?, video_status = 'converting'
            WHERE id = ?
        """, (file_path, individual_assignment_id))
        conn.commit()

        # For now, we'll set it to completed immediately
        # In a real implementation, you would handle video processing separately
        cursor.execute("""
            UPDATE individual_assignments 
            SET video_status = 'completed'
            WHERE id = ?
        """, (individual_assignment_id,))
        conn.commit()

        return jsonify({
            'success': True,
            'message': 'File uploaded successfully',
            'file_path': file_path
        })

    except Exception as e:
        print(f"Error in upload_file: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    
@assignments_bp.route('/check_video_status/<int:individual_assignment_id>')
def check_video_status(individual_assignment_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT video_status 
            FROM individual_assignments 
            WHERE id = ?
        """, (individual_assignment_id,))
        result = cursor.fetchone()
        
        return jsonify({
            'status': result['video_status'] if result else 'not_uploaded'
        })
    except Exception as e:
        print(f"Error checking video status: {e}")
        return jsonify({'error': str(e)}), 500

@assignments_bp.route('/api/scan-folder-for-new-files', methods=['GET'])
@login_required
def scan_folder_for_new_files():
    class_id = request.args.get('class_id', type=int)
    if not class_id:
        return jsonify({"error": "Missing class_id"}), 400

    try:
        conn = get_db()
        cursor = conn.cursor()

        # Step 1: Get class name and semester string
        class_row = cursor.execute("""
            SELECT c.class_name, s.year || '-' || s.term AS semester
            FROM classes c
            JOIN semesters s ON s.id = c.semester_id
            WHERE c.id = ?
        """, (class_id,)).fetchone()

        if not class_row:
            return jsonify({"error": "Class or semester not found"}), 404

        class_name = class_row['class_name']
        semester = class_row['semester']
        base_classes_path = os.getenv("CLASSES_PATH", "C:/Classes")
        folder_path = os.path.normpath(os.path.join(base_classes_path, semester, class_name, "Assignments"))


        if not os.path.exists(folder_path):
            return jsonify({
                "success": False,
                "swal": {
                    "icon": "error",
                    "title": "Folder Not Found",
                    "text": f"Expected folder was missing:\n{folder_path}"
                }
            }), 404


        # Step 2: Load all assignments for the class
        assignment_map = {
            row['name'].strip().lower(): row['id']
            for row in cursor.execute("SELECT id, name FROM assignments WHERE class_id = ?", (class_id,)).fetchall()
        }

        # Step 3: Load all students
        user_map = {
            row['name'].strip().lower(): row['id']
            for row in cursor.execute("SELECT id, name FROM users").fetchall()
        }

        # Step 4: Map phase token to step name
        phase_token_map = {
            'PL': 'Planning',
            'BL': 'Blocking',
            'BP': 'Blocking Plus',
            'P': 'Polish'
        }

        updated = []
        for file in glob.glob(os.path.join(folder_path, "*.webm")):
            filename = os.path.basename(file)
            match = re.match(r"^(.+?)_([^_]+(?: [^_]+)*)_([A-Z]{1,2})_v\d+\.webm$", filename)
            if not match:
                continue  # skip invalid formats

            assignment_name = match.group(1).strip().lower()
            user_name = match.group(2).strip().lower()
            phase_token = match.group(3)

            assignment_id = assignment_map.get(assignment_name)
            user_id = user_map.get(user_name)
            if not assignment_id or not user_id:
                continue  # skip unknown assignments/users

            # Step 5: Find matching individual_assignment
            ia_row = cursor.execute("""
                SELECT id FROM individual_assignments
                WHERE assignment_id = ? AND users_id = ?
            """, (assignment_id, user_id)).fetchone()

            if not ia_row:
                continue

            individual_assignment_id = ia_row['id']

            # Step 6: Save file path + update video status
            cursor.execute("""
                UPDATE individual_assignments
                SET file_path = ?, video_status = 'completed'
                WHERE id = ?
            """, (file, individual_assignment_id))

            # Step 7: Determine target step
            step_row = None
            if phase_token:
                step_row = cursor.execute("""
                    SELECT s.id FROM steps s
                    JOIN assignments a ON s.parent_id = a.parent_step_id
                    WHERE a.id = ? AND s.name = ?
                """, (assignment_id, phase_token_map.get(phase_token))).fetchone()
            else:
                step_row = cursor.execute("""
                    SELECT s.id FROM steps s
                    JOIN assignments a ON s.parent_id = a.parent_step_id
                    WHERE a.id = ? AND s.name NOT LIKE '%Grade%' AND s.name NOT LIKE '%FB%'
                    ORDER BY s.order_num DESC LIMIT 1
                """, (assignment_id,)).fetchone()

            if step_row:
                step_id = step_row['id']

                # Unconditionally update step status to 'Submitted'
                cursor.execute("""
                    UPDATE individual_assignment_statuses
                    SET current_status = 'Submitted'
                    WHERE individual_assignment_id = ? AND step_id = ?
                """, (individual_assignment_id, step_id))

                # [OK] TRIGGER FROM LINKS TABLE
                submitted_node_row = cursor.execute("""
                    SELECT id FROM nodes WHERE name = 'Submitted' AND step_id = ?
                """, (step_id,)).fetchone()

                if submitted_node_row:
                    submitted_node_id = submitted_node_row['id']
                    link_rows = cursor.execute("""
                        SELECT child_node_id, to_flow_id
                        FROM links
                        WHERE parent_node_id = ? AND to_flow_id IS NOT NULL
                    """, (submitted_node_id,)).fetchall()

                    for link in link_rows:
                        child_node_id = link['child_node_id']
                        target_step_id = link['to_flow_id']

                        node_status_row = cursor.execute("""
                            SELECT name FROM nodes WHERE id = ?
                        """, (child_node_id,)).fetchone()

                        if node_status_row:
                            new_status = node_status_row['name']
                            cursor.execute("""
                                UPDATE individual_assignment_statuses
                                SET current_status = ?
                                WHERE individual_assignment_id = ? AND step_id = ?
                            """, (new_status, individual_assignment_id, target_step_id))

            updated.append({"file": filename, "assignment_id": assignment_id, "user_id": user_id})

        conn.commit()
        return jsonify({"success": True, "updated": updated})

    except Exception as e:
        import traceback
        print(" Exception:", traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@assignments_bp.route("/debug/sqlite-version")
def debug_sqlite_version():
    import sqlite3
    return f"SQLite version: {sqlite3.sqlite_version}"



