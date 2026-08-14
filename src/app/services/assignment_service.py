import os
import re
from flask import Blueprint, request, jsonify
from app.database.db import get_db


assignment_bp = Blueprint('assignment', __name__)

CLASS_FOLDER_ROOT = r"\\gaaap1prd01w.ad.uc.edu\Classes"


def find_latest_scene_version(semester_label, class_name, config_filename, display_name):
    """
    Scans the student's Assignments\\Scenes folder for the highest saved
    .ma version, mirroring the naming convention Assignments.py writes to.
    Returns None if there's no config filename yet, the folder doesn't
    exist, or nothing's been saved — never raises (dashboard shouldn't
    break because a network share is briefly unreachable).
    """
    if not config_filename or not semester_label:
        return None

    save_dir = os.path.join(CLASS_FOLDER_ROOT, semester_label, class_name, "Assignments", "Scenes")
    base_name = f"{config_filename}_{display_name}"
    pattern = re.compile(rf"^{re.escape(base_name)}_v(\d+)\.ma$", re.IGNORECASE)

    highest = None
    try:
        for entry in os.listdir(save_dir):
            match = pattern.match(entry)
            if match:
                version = int(match.group(1))
                if highest is None or version > highest:
                    highest = version
    except OSError:
        return None

    return highest


def find_latest_step_scene_version(semester_label, class_name, config_filename, display_name, step_rows, step_codes):
    """
    Scans the student's Assignments\\Scenes folder for the highest saved
    .ma version under the step-based naming convention
    ({base}_{STEP_CODE}_V###.ma), matching what GAASave.py/GAAOpen.py
    actually write (find_latest_scene_version above only ever matched the
    older flat {base}_v#.ma convention, which nothing writes anymore once
    a student starts using GAA Save/Open). Returns (step_name, version)
    for the highest order_num step -- per this assignment's own workflow,
    from step_rows -- that has any file on disk, or (None, None) if
    nothing under this convention exists yet.

    Reflects only what's actually saved on disk, not lock state -- lock
    state is a Maya-tooling concern (see step_locks/launcher_routes.py),
    this is purely "what's the furthest-along file that exists".
    """
    if not config_filename or not semester_label:
        return None, None

    save_dir = os.path.join(CLASS_FOLDER_ROOT, semester_label, class_name, "Assignments", "Scenes")
    base_name = f"{config_filename}_{display_name}"

    try:
        entries = os.listdir(save_dir)
    except OSError:
        return None, None

    # Only steps with a Blocking/Blocking Plus/Polish-style short code get
    # their own scene file -- Planning (PL) and FB-/Grade- pseudo-steps
    # (absent from step_codes) don't, same convention Assignments.py uses.
    file_versioned_codes = {"BL", "BP", "P"}

    best_step_name = None
    best_order_num = None
    best_version = None

    for step in step_rows:
        code = step_codes.get(step["name"])
        if code not in file_versioned_codes:
            continue

        pattern = re.compile(rf"^{re.escape(base_name)}_{re.escape(code)}_V(\d+)\.ma$", re.IGNORECASE)
        highest = None
        for entry in entries:
            match = pattern.match(entry)
            if match:
                version = int(match.group(1))
                if highest is None or version > highest:
                    highest = version

        if highest is not None and (best_order_num is None or step["order_num"] > best_order_num):
            best_order_num = step["order_num"]
            best_step_name = step["name"]
            best_version = highest

    return best_step_name, best_version


def fetch_user_assignments(user_id, semester_id=None):
    conn = get_db()
    query = """
        SELECT ia.id,
               ia.assignment_id,
               a.name AS assignment_name,
               u.name AS user_name,
               ia.start_date,
               ia.completion_date,
               COALESCE(ias.current_status, 'Not Started') AS current_status
        FROM individual_assignments ia
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN users u ON ia.users_id = u.id
        LEFT JOIN individual_assignment_statuses ias ON ia.id = ias.individual_assignment_id
        WHERE ia.users_id = ?
    """
    params = [user_id]

    if semester_id:
        query += """
            AND ia.assignment_id IN (
                SELECT a.id
                FROM assignments a
                JOIN classes c ON a.class_id = c.id
                WHERE c.semester_id = ?
            )
        """
        params.append(semester_id)

    query += " ORDER BY ia.completion_date ASC"

    rows = conn.execute(query, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def fetch_todo_assignments(user_id, semester_id=None):
    conn = get_db()

    try:
        query = """
            SELECT ia.id,
                   a.name AS assignment_name,
                   cl.class_name AS class_name,
                   u.name AS user_name,
                   ia.completion_date,
                   s.name AS step_name,
                   COALESCE(ias.current_status, 'Not Started') AS status
            FROM individual_assignments ia
            JOIN assignments a ON ia.assignment_id = a.id
            JOIN classes cl ON a.class_id = cl.id
            JOIN users u ON ia.users_id = u.id
            LEFT JOIN individual_assignment_statuses ias ON ia.id = ias.individual_assignment_id
            LEFT JOIN steps s ON ias.step_id = s.id
            WHERE ia.users_id = ?
              AND (ias.current_status IS NULL OR ias.current_status NOT IN ('Approved', 'Graded'))
        """

        params = [user_id]

        if semester_id is not None:
            query += " AND cl.semester_id = ?"
            params.append(semester_id)

        query += " ORDER BY ia.completion_date ASC"

        rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    except Exception as e:
        print(f"SQL Error in fetch_todo_assignments: {e}", flush=True)
        return []




def fetch_graded_assignments(user_id):
    conn = get_db()
    query = """
        SELECT ia.id, ia.name AS assignment_name, cl.class_name AS class_name, ias.current_status AS grade
        FROM individual_assignments ia
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN classes cl ON a.class_id = cl.id
        JOIN individual_assignment_statuses ias ON ias.individual_assignment_id = ia.id
        WHERE ia.users_id = ?
          AND ias.current_status IN ('Approved', 'Graded')
        ORDER BY ia.completion_date DESC
    """
    rows = conn.execute(query, (user_id,)).fetchall()
    return rows


def get_user_assignments_by_semester(user_id, semester_id):
    conn = get_db()
    query = """
        SELECT ia.id AS individual_assignment_id,
            ia.assignment_id,
            a.name AS assignment_name,
            a.parent_step_id,
            c.id AS class_id,
            c.class_name,
            ia.completion_date,
            u.name AS display_name,
            sem.year || '-' || sem.term AS semester_label,
            acp.filename AS config_filename
        FROM class_enrollments ce
        JOIN classes c ON ce.class_id = c.id AND c.semester_id = ?
        JOIN assignments a ON a.class_id = c.id
        JOIN individual_assignments ia ON ia.assignment_id = a.id AND ia.users_id = ce.user_id
        JOIN users u ON u.id = ce.user_id
        JOIN semesters sem ON sem.id = c.semester_id
        LEFT JOIN assignment_config_presets acp ON acp.class_id = c.id AND acp.assignment_name = a.name
        WHERE ce.user_id = ?
            AND (? IS NULL OR c.semester_id = ?)
    """
    assignments = conn.execute(query, (semester_id, user_id, semester_id, semester_id)).fetchall()

    step_codes = {
        r["step_name"]: r["step_code"]
        for r in conn.execute("SELECT step_name, step_code FROM step_codes").fetchall()
    }

    results = []

    for row in assignments:
        ia_id = row["individual_assignment_id"]
        flow_id = row["parent_step_id"]

        step_rows = conn.execute(
            "SELECT id, name, order_num FROM steps WHERE parent_id = ? ORDER BY order_num ASC",
            (flow_id,)
        ).fetchall()

        current_file_step, latest_version = find_latest_step_scene_version(
            row["semester_label"], row["class_name"], row["config_filename"], row["display_name"],
            step_rows, step_codes
        )
        if latest_version is None:
            # Fall back to the older flat convention -- assignments that
            # predate step-based versioning, or workflows with no
            # Blocking/Blocking Plus/Polish steps at all (e.g. "Basic
            # Assignment").
            latest_version = find_latest_scene_version(
                row["semester_label"], row["class_name"], row["config_filename"], row["display_name"]
            )

        def get_status(step):
            if not step:
                return None
            status_row = conn.execute(
                """
                SELECT current_status FROM individual_assignment_statuses
                WHERE individual_assignment_id = ? AND step_id = ?
                """,
                (ia_id, step["id"])
            ).fetchone()
            return status_row["current_status"] if status_row else None

        # Pre-fetch FB status
        step_fb = next((s for s in step_rows if s["name"].lower().startswith("fb")), None)
        fb_status = get_status(step_fb)

        # Visible steps = everything except FB/Grade steps
        visible_steps = [
            s for s in step_rows
            if not (s["name"].lower().startswith("fb") or s["name"].lower().startswith("grade"))
        ]

        # Current active step: lowest order_num visible step whose status is neither
        # its own default (not-started) node nor its own terminal node. Compared
        # structurally rather than against a hardcoded status string, since workflows
        # don't share a status vocabulary — this class's "not started" is "Standby",
        # its "done" is "Graded"; another workflow might use "Not Started"/"Approved".
        current_step_name = None
        for step in visible_steps:
            status = get_status(step)
            if not status:
                continue
            step_node_names = [
                n["name"] for n in conn.execute(
                    """
                    SELECT name FROM nodes WHERE step_id = ?
                    ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INT)
                    """,
                    (step["id"],)
                ).fetchall()
            ]
            if not step_node_names:
                continue
            if status != step_node_names[0] and status != step_node_names[-1]:
                current_step_name = step["name"]
                break

        for step in visible_steps:
            step_id = step["id"]
            assignment_status = get_status(step)

            # 🔑 Hybrid grade logic
            step_grades = []

            # Case 1: Look for a grade specifically tied to this step (Grade-<step>)
            grade_step_name = f"Grade-{step['name']}"
            grade_step = next((s for s in step_rows if s["name"] == grade_step_name), None)
            if grade_step:
                status_row = conn.execute(
                    """
                    SELECT current_status FROM individual_assignment_statuses
                    WHERE individual_assignment_id = ? AND step_id = ?
                    """,
                    (ia_id, grade_step["id"])
                ).fetchone()
                step_grades.append(status_row["current_status"] if status_row else "0 - Not completed")
            else:
                # Case 2: Pose-type assignment → collect all Grade-* steps
                pose_grades = []
                for s in step_rows:
                    if s["name"].lower().startswith("grade"):
                        status_row = conn.execute(
                            """
                            SELECT current_status FROM individual_assignment_statuses
                            WHERE individual_assignment_id = ? AND step_id = ?
                            """,
                            (ia_id, s["id"])
                        ).fetchone()
                        pose_grades.append(status_row["current_status"] if status_row else "0 - Not completed")
                if pose_grades:
                    step_grades.extend(pose_grades)

            # Fetch dropdown options
            node_rows = conn.execute(
                """
                SELECT name, color, position FROM nodes
                WHERE step_id = ?
                ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INT)
                """,
                (step_id,)
            ).fetchall()
            dropdown_options = [
                {"name": n["name"], "color": n["color"]} for n in node_rows
            ]

            results.append({
                "assignment_name": row["assignment_name"],
                "class_name": row["class_name"],
                "class_id": row["class_id"],
                "assignment_id": row["assignment_id"],
                "completion_date": row["completion_date"],
                "individual_assignment_id": ia_id,
                "assignment_status": assignment_status,
                "fb_status": fb_status,
                "current_step": current_step_name,
                "grades": step_grades,
                "step_name": step["name"],
                "step_id": step_id,
                "dropdown_options": dropdown_options,
                "latest_version": latest_version,
                "current_file_step": current_file_step
            })

    return {"todo": results}
