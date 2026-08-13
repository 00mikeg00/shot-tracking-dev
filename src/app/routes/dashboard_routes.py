import json
import os
import glob
import mimetypes
from datetime import datetime, timezone
from flask import Blueprint, render_template, session, jsonify, request, send_file, send_from_directory
from app.database.db import get_db
from app.utils.auth_utils import login_required, get_current_semester_id
from app.utils.grade_utils import save_grade_history
from app.services.assignment_service import fetch_user_assignments, fetch_todo_assignments, fetch_graded_assignments
from app.services.assignment_service import get_user_assignments_by_semester as assignment_data_fetcher
from app.services.film_service import get_user_films
from app.services.shot_service import get_todo_shots
from app.services.grade_service import get_student_grade_summary
from collections import defaultdict
from urllib.parse import quote


dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

def is_admin_user():
    perms = session.get("permissions", {})
    return perms.get("classes", 0) >= 3 or perms.get("films", 0) >= 2

def get_active_user_id():
    return session.get("view_as_user_id") or session.get("user_id")

@dashboard_bp.route("/")
@login_required
def dashboard_home():
    """Render the student dashboard HTML page."""
    is_admin = is_admin_user()

    user_id = get_active_user_id()
    semester_id = get_current_semester_id()

    # ðŸ”’ Make user_id + semester_id JSON-safe for Jinja (avoid Undefined crashes)
    try:
        user_id = int(user_id)
    except Exception:
        user_id = 0

    try:
        semester_id = int(semester_id)
    except Exception:
        semester_id = 0

    user_films = get_user_films(user_id)
    todo_shots = get_todo_shots(user_id)
    todo_assignments = fetch_todo_assignments(user_id)
    graded_assignments = fetch_graded_assignments(user_id)

    db = get_db()
    students = []
    if is_admin:
        students = db.execute("""
            SELECT u.id, u.name FROM users u
            JOIN user_groups ug ON u.id = ug.user_id
            JOIN groups g ON ug.group_id = g.id
            WHERE g.section = 'classes'
            ORDER BY u.name
        """).fetchall()

    # Check if admin is impersonating another user
    view_user_name = None
    if is_admin and session.get("view_as_user_id"):
        view_row = db.execute("SELECT name FROM users WHERE id = ?", (session["view_as_user_id"],)).fetchone()
        view_user_name = view_row["name"] if view_row else None

    return render_template(
        "dashboard.html",
        is_admin=is_admin,
        films=user_films,
        shots=todo_shots,
        todo_assignments=todo_assignments,
        graded_assignments=graded_assignments,
        students=students,
        user_id=user_id,
        semester_id=semester_id,
        view_user_name=view_user_name
    )

@dashboard_bp.route("/todo")
@login_required
def todo_page():
    """Load the to-do assignments view for students."""
    return render_template("individual_assignments_view.html", mode="todo")

@dashboard_bp.route("/admin/api/students")
@login_required
def get_all_students():
    if not is_admin_user():
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_db()
    students = conn.execute("""
        SELECT id, name FROM users
        WHERE id IN (SELECT user_id FROM user_groups WHERE group_id = 1)
        ORDER BY name
    """).fetchall()

    return jsonify([dict(row) for row in students])

@dashboard_bp.route("/set_view_user/<int:user_id>")
@login_required
def set_view_user(user_id):
    if not is_admin_user():
        return "Forbidden", 403
    session["view_as_user_id"] = user_id
    return "", 204

#--------------------------------------------------------------------------------------------------------------
#    ASSIGNMENTS
#--------------------------------------------------------------------------------------------------------------

@dashboard_bp.route("/assignments")
@login_required
def assignments_page():
    """Load the full assignments view for instructors/admins."""
    return render_template("individual_assignments_view.html", mode="full")

@dashboard_bp.route("/classes")
@login_required
def get_student_classes():
    student_id = get_active_user_id()
    conn = get_db()
    query = """
        SELECT c.class_name, s.start_date, s.end_date
        FROM classes c
        JOIN class_enrollments ce ON c.id = ce.class_id
        JOIN semesters s ON c.semester_id = s.id
        WHERE ce.user_id = ?
    """
    classes = conn.execute(query, (student_id,)).fetchall()
    return jsonify([dict(cls) for cls in classes])

@dashboard_bp.route("/api/user_assignments/all")
@login_required
def get_user_assignments_all():
    """Returns individual assignments only for the logged-in user."""
    try:
        is_admin = is_admin_user()
        user_id = request.args.get("user_id") if is_admin else get_active_user_id()
        semester_id = request.args.get("semester_id")

        assignments = assignment_data_fetcher(user_id, semester_id)
        return jsonify(assignments)

    except Exception as e:
        print(f"ERROR in get_user_assignments_all: {e}")
        return jsonify({"error": "Server error"}), 500

@dashboard_bp.route("/api/user_assignments/debug", methods=["GET"])
@login_required
def get_user_assignments_debug():
    try:
        user_id = request.args.get("user_id") if is_admin_user() else get_active_user_id()
        semester_id = request.args.get("semester_id")
        return jsonify(assignment_data_fetcher(user_id, semester_id))
    except Exception as e:
        import traceback
        return jsonify({"error": "Internal Server Error", "details": traceback.format_exc()}), 500

@dashboard_bp.route("/api/user_assignments", methods=["GET"])
@login_required
def get_user_assignments_api():
    try:
        user_id = request.args.get("user_id", type=int) if is_admin_user() else get_active_user_id()
        semester_id = request.args.get("semester_id", type=int)

        assignments = assignment_data_fetcher(user_id, semester_id)
        return jsonify(assignments)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return jsonify({"error": "Internal server error", "details": tb}), 500

@dashboard_bp.route("/api/user_classes")
@login_required
def get_user_classes_with_graded_assignments():
    user_id = get_active_user_id()
    semester_id = get_current_semester_id()
    if not semester_id:
        return jsonify([])

    conn = get_db()

    fb_step_ids = [row["id"] for row in conn.execute(
        "SELECT id FROM steps WHERE name LIKE '%FB%'"
    ).fetchall()]
    if not fb_step_ids:
        return jsonify([])

    grade_parent_row = conn.execute("SELECT id FROM steps WHERE name = 'Grade'").fetchone()
    if not grade_parent_row:
        return jsonify([])

    grade_step_ids = [row["id"] for row in conn.execute(
        "SELECT id FROM steps WHERE parent_id = ?", (grade_parent_row["id"],)
    ).fetchall()]
    if not grade_step_ids:
        return jsonify([])

    placeholders_fb = ",".join("?" * len(fb_step_ids))
    placeholders_grade = ",".join("?" * len(grade_step_ids))

    query = f"""
        SELECT c.class_name AS class_name,
               a.name AS assignment_name,
               ias2.current_status AS grade_status
        FROM class_enrollments ce
        JOIN classes c ON ce.class_id = c.id
        JOIN assignments a ON a.class_id = c.id
        JOIN individual_assignments ia ON ia.assignment_id = a.id AND ia.users_id = ce.user_id
        JOIN individual_assignment_statuses ias1 ON ia.id = ias1.individual_assignment_id AND ias1.step_id IN ({placeholders_fb})
        JOIN individual_assignment_statuses ias2 ON ia.id = ias2.individual_assignment_id AND ias2.step_id IN ({placeholders_grade})
        WHERE ce.user_id = ?
          AND ce.semester_id = ?
          AND ias1.current_status = 'Graded'
        ORDER BY c.class_name, a.name
    """

    params = (*fb_step_ids, *grade_step_ids, user_id, semester_id)
    rows = conn.execute(query, params).fetchall()

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["class_name"]].append({
            "assignment_name": row["assignment_name"],
            "status": row["grade_status"]
        })

    result = [{"class_name": cname, "assignments": assigns} for cname, assigns in grouped.items()]
    return jsonify(result)

@dashboard_bp.route("/api/update-status", methods=["POST"])
@login_required
def update_status():
    data = request.get_json()
    task_type = data.get("task_type")  # "assignment", "scene", "shot"
    step_id = data.get("step_id")
    new_status = data.get("new_status")
    task_id = data.get("task_id")

    if not all([task_type, step_id, new_status, task_id]):
        return jsonify({"error": "Missing fields"}), 400

    conn = get_db()

    try:
        if task_type == "assignment":
            # ✅ Save history before overwrite
            save_grade_history(conn, task_id, step_id, new_status)

            conn.execute("""
                UPDATE individual_assignment_statuses
                SET current_status = ?
                WHERE individual_assignment_id = ? AND step_id = ?
            """, (new_status, task_id, step_id))

        elif task_type == "scene":
            conn.execute("""
                UPDATE scene_progress_steps
                SET status = ?
                WHERE scene_id = ? AND step_id = ?
            """, (new_status, task_id, step_id))

            #  Crossflow propagation block (NEW)
            parent_node = conn.execute("""
                SELECT id FROM nodes WHERE step_id = ? AND name = ?
            """, (step_id, new_status)).fetchone()

            if parent_node:
                linked = conn.execute("""
                    SELECT to_flow_id, child_node_id
                    FROM links
                    WHERE parent_node_id = ? AND to_flow_id IS NOT NULL
                """, (parent_node["id"],)).fetchall()

                for row in linked:
                    child_node = conn.execute("""
                        SELECT name FROM nodes WHERE id = ?
                    """, (row["child_node_id"],)).fetchone()

                    if child_node:
                        conn.execute("""
                            UPDATE scene_progress_steps
                            SET status = ?
                            WHERE scene_id = ? AND step_id = ?
                        """, (child_node["name"], task_id, row["to_flow_id"]))

        elif task_type == "shot":
            print(f"[DEBUG] Inserting shot_step_assignments with shot_id={task_id}, step_id={step_id}, status={new_status}")
            # Check existence
            shot_exists = conn.execute("SELECT id FROM shots WHERE id = ?", (task_id,)).fetchone()
            step_exists = conn.execute("SELECT id FROM steps WHERE id = ?", (step_id,)).fetchone()
            print(f"[DEBUG] shot_exists={bool(shot_exists)}, step_exists={bool(step_exists)}")
            thumb_check = conn.execute(
                    "SELECT shot_number FROM shots WHERE id = ?", (task_id,)
                ).fetchone()
            if not thumb_check or "THUMB" in (thumb_check["shot_number"] or "").upper():
                    print(f"[INFO] Skipping thumbnail or placeholder shot (id={task_id})")
                    return jsonify({"message": "Thumbnail ignored"}), 200
            # [OK] Update original step
            conn.execute("""
                INSERT INTO shot_step_assignments (shot_id, step_id, status)
                VALUES (?, ?, ?)
                ON CONFLICT(shot_id, step_id) DO UPDATE SET status = excluded.status
            """, (task_id, step_id, new_status))

            #  Crossflow propagation
            parent_node = conn.execute("""
                SELECT id FROM nodes WHERE step_id = ? AND name = ?
            """, (step_id, new_status)).fetchone()

            if parent_node:
                linked = conn.execute("""
                    SELECT to_flow_id, child_node_id
                    FROM links
                    WHERE parent_node_id = ? AND to_flow_id IS NOT NULL
                """, (parent_node["id"],)).fetchall()

                for row in linked:
                    child_node = conn.execute("""
                        SELECT name FROM nodes WHERE id = ?
                    """, (row["child_node_id"],)).fetchone()

                    if child_node:
                        conn.execute("""
                            INSERT INTO shot_step_assignments (shot_id, step_id, status)
                            VALUES (?, ?, ?)
                            ON CONFLICT(shot_id, step_id) DO UPDATE SET status = excluded.status
                        """, (task_id, row["to_flow_id"], child_node["name"]))


        else:
            return jsonify({"error": f"Unsupported task_type: {task_type}"}), 400

        conn.commit()
        return jsonify({"message": "Status updated successfully"})

    except Exception as e:
        print("Update error:", e)
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/api/individual-assignments")
@login_required
def api_individual_assignments():
    try:
        semester_id = request.args.get("semester_id", type=int)
        user_id = request.args.get("user_id", type=int)

        if not semester_id or not user_id:
            return jsonify({"error": "Missing semester_id or user_id"}), 400

        todo = fetch_todo_assignments(user_id, semester_id=semester_id)

        for row in todo:
            print("Row:", dict(row))
        return jsonify([dict(row) for row in todo])

    except Exception as e:
        import traceback
        traceback.print_exc()
        print("ðŸ”¥ API Crash:", e, flush=True)
        return jsonify({"error": str(e)}), 500

# --------------------------------------------------------------------------------------------------------------
#    GRADES
# --------------------------------------------------------------------------------------------------------------

@dashboard_bp.route("/api/grade_summary")
@login_required
def grade_summary():
    """Return grade summary for the logged-in student for a specific class."""
    class_id = request.args.get("class_id", type=int)
    if not class_id:
        return jsonify({"error": "Missing class_id"}), 400

    user_id = get_active_user_id()
    summary = get_student_grade_summary(user_id, class_id)

    if not summary:
        return jsonify({"error": "No grade data found"}), 404

    return jsonify(summary)

@dashboard_bp.route("/api/grade_history/<int:individual_assignment_id>")
@login_required
def get_grade_history(individual_assignment_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT gh.old_grade, gh.new_grade, gh.changed_at, s.name as step_name
        FROM grade_history gh
        JOIN steps s ON gh.step_id = s.id
        WHERE gh.individual_assignment_id = ?
        ORDER BY gh.changed_at DESC
    """, (individual_assignment_id,)).fetchall()

    return jsonify({
        "history": [dict(r) for r in rows]
    })

# --------------------------------------------------------------------------------------------------------------
#    REVIEWS
# --------------------------------------------------------------------------------------------------------------

@dashboard_bp.route("/api/reviews/<assignment_name>", defaults={"user_name": None})
@dashboard_bp.route("/api/reviews/<assignment_name>/<user_name>")
@login_required
def check_review(assignment_name, user_name):
    review_dir = r"\\GAAAP1PRD01W\Reviews"

    # Get optional step code (?step=BL)
    step_code = request.args.get("step")

    # Debug logs
    print(f"[DEBUG] assignment_name (raw): {assignment_name}", flush=True)
    print(f"[DEBUG] user_name (raw): {user_name}", flush=True)
    print(f"[DEBUG] step_code (raw): {step_code}", flush=True)

    # Fallback to session if user_name missing/undefined
    if not user_name or user_name.lower() == "undefined":
        user_name = session.get("view_as_user_name") or session.get("username")
        print(f"[DEBUG] user_name replaced from session: {user_name}", flush=True)

    safe_assignment = assignment_name  # keep spaces to match real filenames


    # ✅ Build both space and underscore patterns for user name
    patterns = []
    if user_name:
        safe_user_spaces = user_name  # keep spaces
        safe_user_underscores = user_name.replace(" ", "_")

        patterns.append(os.path.join(review_dir, "*", f"{safe_assignment}_{safe_user_spaces}_*.mp4"))
        patterns.append(os.path.join(review_dir, "*", f"{safe_assignment}_{safe_user_underscores}_*.mp4"))
    else:
        patterns.append(os.path.join(review_dir, "*", f"{safe_assignment}_*.mp4"))

    print(f"[DEBUG] Glob patterns built: {patterns}", flush=True)

    matches = []
    for pat in patterns:
        found = glob.glob(pat)
        print(f"[DEBUG] Matches for {pat}: {found}", flush=True)
        matches.extend(found)

    # 🔎 Filter by step code if provided
    if step_code:
        matches = [m for m in matches if f"_{step_code}_" in os.path.basename(m)]
        print(f"[DEBUG] After step filter ({step_code}): {matches}", flush=True)

        # Strict mode: if no matches after filtering, stop here
        if not matches:
            return jsonify({"exists": False})

    if matches:
        matches.sort(key=os.path.getmtime, reverse=True)

        reviews = []
        for idx, m in enumerate(matches[:2]):  # newest + one older
            rel_path = m.replace(review_dir, "").lstrip("\\/")
            rel_path = rel_path.replace(os.sep, "/")
            reviews.append({
                "path": f"/dashboard/Reviews/{quote(rel_path)}",
                "is_latest": (idx == 0)
            })

        return jsonify({"exists": True, "reviews": reviews})

    return jsonify({"exists": False})


@dashboard_bp.route("/Reviews/<path:filename>")
@login_required
def serve_review_file(filename):
    review_dir = r"\\GAAAP1PRD01W\Reviews"
    try:
        return send_from_directory(review_dir, filename, as_attachment=False)
    except FileNotFoundError:
        return jsonify({"error": "Not Found"}), 404

@dashboard_bp.route("/play_review")
@login_required
def play_review():
    """
    Stream the review video directly in browser.
    """
    path = request.args.get("path")
    if not path or not os.path.exists(path):
        return "Review not found", 404

    mimetype, _ = mimetypes.guess_type(path)
    return send_file(path, mimetype=mimetype, as_attachment=False)


#--------------------------------------------------------------------------------------------------------------
#    FILMS
#--------------------------------------------------------------------------------------------------------------

@dashboard_bp.route("/films")
@login_required
def get_student_films():
    """Fetch films for a specific user (used by dashboard JS)."""
    user_id = session.get("view_as_user_id") or session.get("user_id")
    conn = get_db()

    rows = conn.execute("""
        SELECT f.name AS title, g.name AS role
        FROM film_crew fc
        JOIN films f ON f.id = fc.film_id
        JOIN groups g ON fc.group_id = g.id
        WHERE fc.user_id = ?
        ORDER BY f.id DESC
    """, (user_id,)).fetchall()

    return jsonify([dict(row) for row in rows])

@dashboard_bp.route("/films/shots")
@login_required
def get_user_film_shots():
    user_id = session.get("view_as_user_id") or session.get("user_id")
    user_name = session.get("view_as_user_name") or session.get("username")
    print(f"ðŸ§ª EFFECTIVE user_name used to match thumbnails = '{user_name}'")
    conn = get_db()

    film_rows = conn.execute("""
        SELECT f.id, f.name AS title, g.name AS role
        FROM film_crew fc
        JOIN films f ON f.id = fc.film_id
        JOIN groups g ON fc.group_id = g.id
        WHERE fc.user_id = ?
        ORDER BY f.id DESC
    """, (user_id,)).fetchall()

    film_map = {}

    for film in film_rows:
        film_id = film["id"]
        if film_id in film_map:
            continue

        shots = conn.execute("""
            SELECT s.id AS shot_id, s.shot_number, sc.scene_number, sc.id AS scene_id
            FROM scenes sc
            JOIN shots s ON s.scene_id = sc.id
            WHERE sc.film_id = ?
            ORDER BY s.shot_number
        """, (film_id,)).fetchall()

        shot_ids = [row["shot_id"] for row in shots]

        excluded_step_ids = {
            row["id"] for row in conn.execute(
                "SELECT id FROM steps WHERE LOWER(name) LIKE '%thumbnail%'"
            )
        }

        all_statuses = conn.execute(f"""
            SELECT shot_id, step_id, status
            FROM shot_step_assignments
            WHERE shot_id IN ({','.join(['?'] * len(shot_ids))})
        """, tuple(shot_ids)).fetchall() if shot_ids else []

        all_statuses = [
            row for row in all_statuses if row["step_id"] not in excluded_step_ids
        ]

        all_assignments = conn.execute(f"""
            SELECT sa.shot_id, sa.step_id, sa.assigned_to, sa.due_date, st.name AS step_name
            FROM shot_step_assignments sa
            JOIN steps st ON sa.step_id = st.id
            WHERE sa.assigned_to IN (?, ?) AND sa.shot_id IN ({','.join(['?'] * len(shot_ids))})
        """, (user_id, user_name, *shot_ids)).fetchall() if shot_ids else []

        all_assignments = [
            row for row in all_assignments if row["step_id"] not in excluded_step_ids
        ]

        # [OK] SCENE-level thumbnail steps WITH STATUS now included
        scene_assignments = conn.execute("""
            SELECT sps.scene_id,
                   sc.scene_number,
                   sps.step_id,
                   sps.status,
                   sps.assigned_to,
                   sps.due_date,
                   st.name AS step_name
            FROM scene_progress_steps sps
            JOIN steps st ON sps.step_id = st.id
            JOIN scenes sc ON sc.id = sps.scene_id
            WHERE st.name LIKE '%thumbnail%'
              AND (LOWER(sps.status) != 'approved' OR sps.status IS NULL)
              AND sps.assigned_to = ?
        """, (user_id,)).fetchall()

        print("ðŸ§¨ FINAL SCENE_ASSIGNMENTS", [dict(r) for r in scene_assignments])

        scene_assignments = [
            row for row in scene_assignments
            if row["assigned_to"] and str(row["assigned_to"]).strip() in {str(user_id), user_name.strip().lower()}
        ]

        print("ðŸ§¨ RAW SCENE THUMBNAILS:", [dict(r) for r in scene_assignments])

        all_assignments.extend(scene_assignments)

        status_lookup = {
            (row["shot_id"], row["step_id"]): row["status"]
            for row in all_statuses
        }

        # [OK] FIX: Safe keying + row.get for sqlite rows
        assignment_lookup = {
            (row["shot_id"] if "shot_id" in row.keys() else None, row["step_id"]): row
            for row in all_assignments
            if (
                isinstance(row["assigned_to"], str) and str(row["assigned_to"]).strip().lower() == str(user_name).strip().lower()
            ) or (
                isinstance(row["assigned_to"], (int, str)) and str(row["assigned_to"]).strip() == str(user_id)
            )
        }

        steps_map = {}
        for row in all_assignments:
            step_id = row["step_id"]
            if step_id not in steps_map:
                nodes = conn.execute("""
                    SELECT name, color, position
                    FROM nodes
                    WHERE step_id = ?
                    ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INT)
                """, (step_id,)).fetchall()
                steps_map[step_id] = [dict(n) for n in nodes]

        shot_list = []

        # â–¶ Real shots
        for shot in shots:
            shot_steps = []
            for (a_shot_id, step_id), assign in assignment_lookup.items():
                if a_shot_id != shot["shot_id"]:
                    continue

                status = status_lookup.get((a_shot_id, step_id))
                if not status or status.strip().lower() == "approved":
                    continue  # [OK] skip if approved or empty

                status_color = next(
                    (opt["color"] for opt in steps_map.get(step_id, []) if opt["name"] == status),
                    "#cccccc"
                )

                shot_steps.append({
                    "step_id": step_id,
                    "step_name": assign["step_name"],
                    "status": status,
                    "status_color": status_color,
                    "dropdown_options": steps_map.get(step_id, []),
                    "due_date": assign["due_date"],
                    "assigned_to": assign["assigned_to"]
                })

            if shot_steps:
                shot_list.append({
                    "shot_id": shot["shot_id"],
                    "shot_number": shot["shot_number"],
                    "scene_number": shot["scene_number"],
                    "steps": shot_steps
                })

        # â–¶ Scene-only thumbnails (no shot_id)
        for (a_shot_id, step_id), assign in assignment_lookup.items():
            if a_shot_id is not None:
                continue

            status = assign["status"] if "status" in assign.keys() else ""
            if not status or status.strip().lower() == "approved":
                continue  # [OK] skip if approved or empty

            scene_data = conn.execute("""
                SELECT sc.scene_number, sc.id AS scene_id
                FROM scene_progress_steps sps
                JOIN scenes sc ON sc.id = sps.scene_id
                WHERE sps.step_id = ?
            """, (step_id,)).fetchall()

            for scene_row in scene_data:
                status_color = next(
                    (opt["color"] for opt in steps_map.get(step_id, []) if opt["name"] == status),
                    "#cccccc"
                )

                shot_list.append({
                    "shot_id": None,
                    "shot_number": "-",
                    "scene_number": scene_row["scene_number"],
                    "scene_id": scene_row["scene_id"],
                    "steps": [{
                        "step_id": step_id,
                        "step_name": assign["step_name"],
                        "status": status,
                        "status_color": status_color,
                        "dropdown_options": steps_map.get(step_id, []),
                        "due_date": assign["due_date"],
                        "assigned_to": assign["assigned_to"],
                        "scene_id": scene_row["scene_id"]
                    }]
                })



        film_map[film_id] = {
            "title": film["title"],
            "role": film["role"],
            "shots": shot_list
        }

    # [OK] fail-safe protection
    try:
        return jsonify(list(film_map.values()))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/api/update_shot_status", methods=["POST"])
@login_required
def update_shot_status():
    data = request.get_json()
    step_id = data.get("step_id")
    new_status = data.get("new_status")
    task_type = data.get("task_type")
    task_id = data.get("task_id")
    user_id = session.get("view_as_user_id") or session.get("user_id")

    conn = get_db()

    try:
        if task_type == "shot":
            result = conn.execute("""
                UPDATE shot_step_assignments
                SET status = ?
                WHERE step_id = ? AND shot_id = ? AND assigned_to = ?
            """, (new_status, step_id, task_id, user_id))
        elif task_type == "scene":


            result = conn.execute("""
                UPDATE scene_progress_steps
                SET status = ?
                WHERE step_id = ? AND scene_id = ? AND assigned_to = ?
            """, (new_status, step_id, task_id, user_id))


        else:
            return jsonify({"success": False, "message": "Invalid task_type"}), 400

        conn.commit()
        print("[OK] Status updated:", task_type, task_id, "â†’", new_status)
        return jsonify({"success": True})

    except Exception as e:
        print("âŒ Update error:", e)
        return jsonify({"success": False, "message": str(e)}), 500

@dashboard_bp.route("/api/approved_film_items", methods=["GET"])
@login_required
def get_approved_film_items():
    user_id = session.get("view_as_user_id") or session.get("user_id")
    conn = get_db()

    results = conn.execute("""
        SELECT f.id AS film_id, f.name AS film_name,
               s.id AS scene_id, s.scene_number,
               st.name AS step_name, sps.status
        FROM films f
        JOIN scenes s ON s.film_id = f.id
        JOIN scene_progress_steps sps ON s.id = sps.scene_id
        JOIN steps st ON st.id = sps.step_id
        JOIN film_crew fc ON fc.film_id = f.id
        WHERE fc.user_id = ?
          AND f.archived = 0
          AND sps.status = 'Approved'
          AND st.name IN ('Thumbnails', 'FB Thumbnails')
        ORDER BY f.name, s.scene_number
    """, (user_id,)).fetchall()

    film_map = {}
    for row in results:
        fid = row["film_id"]
        film_name = row["film_name"]
        scene_number = row["scene_number"]
        step_name = row["step_name"]

        file_path = ""

        if step_name == "Thumbnails":
            pattern = f"D:/Films/{film_name}/Thumbnails/Lost_{scene_number}_THUMB*_R.mov"
        elif step_name == "Storyboards":
            pattern = f"D:/Films/{film_name}/Thumbnails/Lost_{scene_number}_SB*_R.mov"

        # ðŸ§  Pick the most recent matching file
        matching_files = glob.glob(pattern)
        if matching_files:
            file_path = max(matching_files, key=os.path.getmtime)  # most recent

        film_map.setdefault(fid, {
            "film_id": fid,                # [OK] added
            "film_name": film_name,
            "scenes": []
        })

        film_map[fid]["scenes"].append({
            "scene_number": scene_number,
            "step": step_name,
            "status": row["status"],
            "file_path": file_path         # [OK] added
        })


    return jsonify(list(film_map.values()))

@dashboard_bp.route("/approved_file")
@login_required
def serve_approved_film_file():
    path = request.args.get("path")
    if not path or not os.path.exists(path):
        return "File not found", 404

    mimetype, _ = mimetypes.guess_type(path)
    return send_file(path, mimetype=mimetype, as_attachment=False)

#--------------------------------------------------------------------------------------------------------------
#    ASSETS
#--------------------------------------------------------------------------------------------------------------
def _resolve_active_asset_steps(conn, asset_ids):
    """
    {asset_id: active_step_id}, using the same "lowest order_num unlocked
    among Modeling/Texture-Surface/Rigging, else the last one if all
    locked" algorithm as Assets.py's resolve_current_step() -- computed
    server-side here (not per-viewing-user's own assigned rows) because a
    step's assignee can differ per step, so one user's own rows alone
    don't carry enough context to know what's actually next for that asset.
    """
    if not asset_ids:
        return {}

    placeholders = ",".join("?" * len(asset_ids))
    rows = conn.execute(f"""
        SELECT
            asa.asset_id, s.id AS step_id, s.order_num, sc.step_code AS short_code,
            sl.locked
        FROM asset_step_assignments asa
        JOIN steps s ON s.id = asa.step_id
        LEFT JOIN step_codes sc ON sc.step_name = s.name
        LEFT JOIN step_locks sl
            ON sl.entity_type = 'asset_step' AND sl.entity_id = asa.asset_id AND sl.step_id = s.id
        WHERE asa.asset_id IN ({placeholders})
          AND sc.step_code IN ('MOD', 'TEX', 'RIG')
    """, asset_ids).fetchall()

    by_asset = {}
    for row in rows:
        by_asset.setdefault(row["asset_id"], []).append(row)

    active = {}
    for asset_id, steps in by_asset.items():
        unlocked = [s for s in steps if not s["locked"]]
        chosen = min(unlocked, key=lambda s: s["order_num"]) if unlocked else max(steps, key=lambda s: s["order_num"])
        active[asset_id] = chosen["step_id"]

    return active


@dashboard_bp.route("/api/user_assets")
def get_user_assets():
    user_id = session.get("view_as_user_id") or session.get("user_id")

    if not user_id:
        return jsonify([])

    query = """
    SELECT
      a.id AS asset_id,
      a.name,
      a.category,
      asa.step_id,
      asa.status,
      asa.due_date,
      asa.node_id,
      s.name AS step_name,
      n.name AS node_name,
      n.color AS node_color,
      f.name AS film_name,
        (
            SELECT json_group_array(
            json_object(
                'node_id', nodes.id,
                'name', nodes.name,
                'color', nodes.color,
                'position', nodes.position
            )
            )
            FROM nodes
            WHERE nodes.step_id = asa.step_id
            ORDER BY CAST(SUBSTR(nodes.position, INSTR(nodes.position, ' ') + 1) AS FLOAT)
        ) AS step_nodes
    FROM asset_step_assignments asa
    JOIN assets a ON asa.asset_id = a.id
    JOIN steps s ON asa.step_id = s.id
    JOIN nodes n ON asa.node_id = n.id
    JOIN films f ON a.film_id = f.id
    WHERE asa.assigned_user = ?
      AND f.archived = 0
    ORDER BY asa.due_date IS NULL, asa.due_date
    """

    conn = get_db()
    rows = conn.execute(query, (user_id,)).fetchall()
    data = [dict(row) for row in rows]

    # Fully Shot Ready assets are done -- nothing left for the student to
    # do, and leaving them clickable here risks exactly the kind of
    # after-the-fact reopen that's supposed to go through the coordinator's
    # override picker instead (see individual_assets_view.html), not the
    # student's own dashboard.
    shot_ready_ids = {
        row["asset_id"] for row in conn.execute("""
            SELECT asa.asset_id
            FROM asset_step_assignments asa
            JOIN steps s ON s.id = asa.step_id
            WHERE s.name = 'Shot Ready' AND asa.status = 'Shot Ready'
        """).fetchall()
    }
    data = [item for item in data if item["asset_id"] not in shot_ready_ids]

    # A Done Proxy is done -- only that row drops off (unlike Shot Ready,
    # which removes the whole asset), since Modeling/Texture-Surface/
    # Rigging for the same asset are a separate, still-relevant track.
    # Reopening a finished Proxy goes through the coordinator's override
    # picker (individual_assets_view.html), not the student's dashboard.
    data = [item for item in data if not (item["step_name"] == "Proxy" and item["status"] == "Done")]

    for item in data:
        try:
            item["step_nodes"] = json.loads(item["step_nodes"]) if item["step_nodes"] else []
        except Exception:
            item["step_nodes"] = []

    active_steps = _resolve_active_asset_steps(conn, list({item["asset_id"] for item in data}))
    for item in data:
        item["is_active_step"] = active_steps.get(item["asset_id"]) == item["step_id"]

    return jsonify(data)

# FB step -> the production step it gates. Only these two: FB Rigging's
# Approved is the coordinator's separate "make it Shot Ready" action
# (already handled elsewhere, per explicit confirmation), not a
# step_locks unlock -- Rigging is the last file-versioned step, there's
# nothing after it in FILE_VERSIONED_STEP_CODES to unlock.
ASSET_FB_UNLOCKS_STEP = {
    "FB Modeling": "Modeling",
    "FB Texture/Surface": "Texture/Surface",
}


@dashboard_bp.route("/api/update_asset_status", methods=["POST"])
def update_asset_status():
    data = request.get_json()
    asset_id = data.get("asset_id")
    step_id = data.get("step_id")
    node_id = data.get("node_id")

    if not all([asset_id, step_id, node_id]):
        return jsonify({"error": "Missing fields"}), 400

    conn = get_db()

    # Fetch the node name for status field
    node = conn.execute(
        "SELECT name FROM nodes WHERE id = ?",
        (node_id,)
    ).fetchone()

    if not node:
        return jsonify({"error": "Invalid node ID"}), 400

    node_name = node["name"]

    query = """
    UPDATE asset_step_assignments
    SET node_id = ?, status = ?, updated_at = CURRENT_TIMESTAMP
    WHERE asset_id = ? AND step_id = ?
    """

    conn.execute(query, (node_id, node_name, asset_id, step_id))

    # FB Modeling/FB Texture-Surface reaching Approved is what unlocks the
    # NEXT production step (Modeling -> Texture-Surface, Texture-Surface ->
    # Rigging). Writes into the same step_locks table (entity_type=
    # 'asset_step') that Assets.py's resolve_current_step() reads, so this
    # is the actual mechanism that makes the dashboard's OPEN button (and
    # is_active_step gating) advance -- not a separate flag.
    if node_name == "Approved":
        fb_step_row = conn.execute("SELECT name FROM steps WHERE id = ?", (step_id,)).fetchone()
        production_step_name = ASSET_FB_UNLOCKS_STEP.get(fb_step_row["name"]) if fb_step_row else None

        if production_step_name:
            production_step = conn.execute("""
                SELECT s.id
                FROM asset_step_assignments asa
                JOIN steps s ON s.id = asa.step_id
                WHERE asa.asset_id = ? AND s.name = ?
            """, (asset_id, production_step_name)).fetchone()

            if production_step:
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                approver_id = session.get("user_id")
                conn.execute("""
                    INSERT INTO step_locks (entity_type, entity_id, step_id, locked, locked_by, locked_at)
                    VALUES ('asset_step', ?, ?, 1, ?, ?)
                    ON CONFLICT(entity_type, entity_id, step_id)
                    DO UPDATE SET locked = 1, locked_by = excluded.locked_by, locked_at = excluded.locked_at
                """, (asset_id, production_step["id"], approver_id, now))

    conn.commit()

    return jsonify({"success": True})

# --------------------------------------------------------------------------------------------------------------
#    SCRIPTS
# --------------------------------------------------------------------------------------------------------------

@dashboard_bp.route("/films/get_script/<film_name>")
@login_required
def get_film_script(film_name):
    """Serve the script file for a given film."""
    base_dir = r"C:\Films"
    script_dir = os.path.join(base_dir, film_name, "Scripts")

    if not os.path.exists(script_dir):
        return jsonify({"error": "Script folder not found"}), 404

    # Look for any PDF, DOCX, or TXT file inside Scripts
    for file in os.listdir(script_dir):
        if file.lower().endswith((".pdf", ".docx", ".txt")):
            return send_from_directory(script_dir, file, as_attachment=False)

    return jsonify({"error": "No script file found"}), 404
