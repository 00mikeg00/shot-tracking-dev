import os, re, glob, shutil, sqlite3, json as stdjson
import zipfile
import traceback
import urllib.parse
from flask import Blueprint, send_file, request, jsonify, json, session, make_response
from app.utils.get_files_for_review import get_assignments_for_review, get_films_for_review, get_all_film_files
from app.utils.auth_utils import login_required
from app.utils.grade_utils import save_grade_history
from app.database.db import get_db
from urllib.parse import unquote
from flask_cors import CORS
from datetime import datetime

import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATABASE_PATH = os.path.join(BASE_DIR, "database", "app.db")

review_routes = Blueprint("review_routes", __name__)

def copy_to_reviewed_thumbnails(src_path, film_name, scene_number):
    reviewed_dir = os.path.join(
        r"\\GAAAP1PRD01W\Films",
        film_name,
        "Thumbnails",
        "Reviewed"
    )
    os.makedirs(reviewed_dir, exist_ok=True)

    dst = os.path.join(reviewed_dir, os.path.basename(src_path))
    shutil.copy2(src_path, dst)
    return dst

@review_routes.after_request
def apply_cors_headers(response):
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
    return response


BASE_VIDEO_DIR = r"\\GAAAP1PRD01W\Classes"
BASE_ASSIGNMENT_DIR = r"\\GAAAP1PRD01W\Classes"
BASE_FILM_DIR = r"\\GAAAP1PRD01W\Films"


INVALID_DIR = os.path.join(BASE_VIDEO_DIR, "invalid")


def _to_builtin(obj):
    if isinstance(obj, sqlite3.Row):
        return {k: obj[k] for k in obj.keys()}
    if isinstance(obj, dict):
        return {k: _to_builtin(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_builtin(v) for v in obj]
    return obj

def jsonify_safe(payload, status=200):
    return jsonify(_to_builtin(payload)), status

def _log(tag, **kv):
    # why: single place for consistent, grep-able logs
    items = " ".join(f"{k}={v}" for k, v in kv.items())
    print(f"[{tag}] {items}")

# ----------------------------------------------------------------------------------------------------------------------
# GET FILES
# ----------------------------------------------------------------------------------------------------------------------

@review_routes.route("/get_video", methods=["GET"])
def get_video():
    import os, re, glob, urllib.parse

    raw_path = request.args.get("path")
    if not raw_path:
        return "Missing file path", 400

    # --- Decode / normalize ---
    cleaned = urllib.parse.unquote(raw_path)
    if "/review/get_video?path=" in cleaned:
        cleaned = cleaned.split("/review/get_video?path=")[-1]
        cleaned = urllib.parse.unquote(cleaned)

    cleaned = cleaned.replace("/", os.sep)
    cleaned = os.path.normpath(cleaned)
    print(f"🎬 Cleaned path → {cleaned}")

    # --- Direct hit ---
    if os.path.exists(cleaned):
        ext = os.path.splitext(cleaned)[1].lower()
        mime_type = {
            ".webm": "video/webm",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".png": "image/png",
        }.get(ext, "application/octet-stream")
        return send_file(cleaned, mimetype=mime_type, as_attachment=False)

    # --- Version-auto-resolve fallback ---
    base_dir = os.path.dirname(cleaned)
    name_no_ext, ext = os.path.splitext(os.path.basename(cleaned))
    prefix = re.split(r"_v\d+.*$", name_no_ext, maxsplit=1)[0]

    # 🔍 Look for any matching v# file (ignore _R)
    pattern = os.path.join(base_dir, f"{prefix}_v*.webm")
    candidates = glob.glob(pattern)
    print(f"🔍 Looking for candidates: {pattern}")
    print(f"🔍 Found {len(candidates)} candidate(s)")

    if candidates:
        def version_key(p):
            m = re.search(r"_v(\d+)", os.path.basename(p))
            return int(m.group(1)) if m else -1

        # sort by version number
        candidates.sort(key=version_key)
        resolved = candidates[-1]
        print(f"✅ Resolved to latest version → {resolved}")

        mime_type = {
            ".webm": "video/webm",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".png": "image/png",
        }.get(os.path.splitext(resolved)[1].lower(), "application/octet-stream")
        return send_file(resolved, mimetype=mime_type, as_attachment=False)

    # --- Nothing found ---
    print(f"❌ No file found for pattern: {pattern}")
    return f"File not found: {cleaned}", 404


@review_routes.route("/api/get_friendly_name", methods=["GET"])
def get_friendly_name():
    login = request.args.get("login")
    if not login:
        return jsonify({"error": "Missing login"}), 400

    conn = get_db()
    cursor = conn.cursor()
    row = cursor.execute("SELECT name FROM users WHERE login_name = ?", (login,)).fetchone()
    conn.close()

    if row:
        return jsonify({"friendly_name": row["name"]})
    else:
        return jsonify({"friendly_name": login})

@review_routes.route("/get_files_for_review", methods=["GET"])
def get_files_for_review():
    conn = get_db()
    cursor = conn.cursor()

    assignments = get_assignments_for_review()
    films = get_films_for_review(cursor)  # ✅ pass cursor now

    films_reviewed = [
        file
        for scenes in films["reviewed"].values()
        for shot_list in scenes.values()
        for file in shot_list
    ]

    conn.close()

    return jsonify({
        "assignments": assignments,
        "films": films["to_review"],
        "films_reviewed": films_reviewed
    })

@review_routes.route("/get_annotations", methods=["GET"])
def get_annotations():
    individual_assignment_id = request.args.get("id")

    if not individual_assignment_id:
        return jsonify({"error": "Missing individual_assignment_id"}), 400

    conn = get_db()
    cursor = conn.cursor()

    try:
        row = cursor.execute("""
            SELECT a.name AS assignment_name, c.class_name, u.login_name AS username, s.year, s.term
            FROM individual_assignments ia
            JOIN assignments a ON ia.assignment_id = a.id
            JOIN classes c ON a.class_id = c.id
            JOIN semesters s ON c.semester_id = s.id
            LEFT JOIN users u ON ia.users_id = u.id
            WHERE ia.id = ?
        """, (individual_assignment_id,)).fetchone()

        if not row:
            return jsonify({"error": "Assignment not found"}), 404

        if not row["username"]:
            return jsonify({"error": "User not found for assignment"}), 404


        semester_folder = f"{row['year']}-{row['term']}"
        assignment_base = f"{row['assignment_name']}_{row['username']}"
        class_path = os.path.join(BASE_VIDEO_DIR, semester_folder, row["class_name"], "Assignments")

        if not os.path.exists(class_path):
            return jsonify({"error": "Path not found"}), 404

        json_files = [
            f for f in os.listdir(class_path)
            if f.startswith(assignment_base) and f.endswith("_R.json")
        ]

        if not json_files:
            return jsonify({"annotations": {}})

        json_files.sort(reverse=True)
        latest_json_path = os.path.join(class_path, json_files[0])

        with open(latest_json_path, "r", encoding="utf-8") as f:
            annotations = json.load(f)
            return jsonify({"annotations": annotations})

    except Exception as e:
        print("ðŸ”¥ get_annotations error:", e)
        return jsonify({"annotations": {}, "error": str(e)}), 500

    finally:
        conn.close()

@review_routes.route("/get_annotation_file", methods=["GET"])
def get_annotation_file():
    path = request.args.get("path")
    if not path or not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        print(f"âŒ Failed to read JSON from {path}: {e}")
        return jsonify({"error": "Could not read annotation file"}), 500

@review_routes.route("/get_all_step_names", methods=["GET"])
def get_all_step_names():
    prefix = request.args.get("prefix", "")
    conn = get_db()
    cursor = conn.cursor()

    results = cursor.execute(
        "SELECT name FROM steps WHERE name LIKE ? ORDER BY name",
        (f"{prefix}%",)
    ).fetchall()

    return jsonify({"step_names": [r["name"] for r in results]})

@review_routes.route("/step_codes", methods=["GET"])
def get_step_codes():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT step_name, step_code FROM step_codes ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    code_mapping = {row["step_code"]: row["step_name"] for row in rows}
    return jsonify(code_mapping)

@review_routes.route('/api/assignment-review-files', methods=['GET'])
def get_review_files():
    all_assignments = {}
    conn = get_db()
    cursor = conn.cursor()

    assignments = get_assignments_for_review()
    films_raw = get_films_for_review(cursor)
    all_films_data = get_all_film_files()

    # Filter out .json and non-video files
    video_exts = ('.webm', '.mp4', '.mov', '.avi')
    all_films_data = {
        k: [f for f in v if f.lower().endswith(video_exts)]
        for k, v in all_films_data.items()
    }

    # 🔹 Remove any shots marked as CUT in films_raw
    cut_files = set()
    for category in ("reviewed", "to_review"):
        film_group = films_raw.get(category, {})
        for film_name, scenes in film_group.items():
            for scene_name, files in scenes.items():
                for file in files:
                    if isinstance(file, dict):
                        # If it's a dict with status info
                        if file.get("status", "").lower() == "cut":
                            cut_files.add(file.get("file_name"))
                    elif isinstance(file, str) and "_CUT" in file.upper():
                        # Fallback if filename contains CUT tag
                        cut_files.add(file)

    # 🧹 Exclude CUT shots from all_films_data
    all_films_data = {
        k: [f for f in v if os.path.basename(f) not in cut_files]
        for k, v in all_films_data.items()
    }

    print(f"🪓 Excluding {len(cut_files)} cut shots:")
    for f in cut_files:
        print("   ❌", f)

    for semester_folder in os.listdir(BASE_ASSIGNMENT_DIR):
        semester_path = os.path.join(BASE_ASSIGNMENT_DIR, semester_folder)
        if not os.path.isdir(semester_path):
            continue

        for class_folder in os.listdir(semester_path):
            assignments_path = os.path.join(semester_path, class_folder, "Assignments")
            if not os.path.isdir(assignments_path):
                continue

            reviewed_files = [
                f for f in os.listdir(assignments_path)
                if f.endswith(".mov") or f.endswith("_R.webm")
            ]
            if not reviewed_files:
                continue

            key = f"{semester_folder} - {class_folder}"
            all_assignments[key] = []

            for f in reviewed_files:
                file_path = os.path.join(assignments_path, f).replace("\\", "/")
                base_name = os.path.splitext(f)[0]
                match = re.match(r"(.+?)_(.+?)_v\d+", base_name)
                if not match:
                    continue

                assignment_name, username = match.groups()

                try:
                    cursor.execute("""
                        SELECT ia.id
                        FROM individual_assignments ia
                        JOIN assignments a ON ia.assignment_id = a.id
                        JOIN classes c ON a.class_id = c.id
                        JOIN semesters s ON c.semester_id = s.id
                        JOIN users u ON ia.users_id = u.id
                        WHERE a.name = ?
                          AND u.name = ?
                          AND c.class_name = ?
                          AND (s.year || '-' || s.term) = ?
                        LIMIT 1
                    """, (assignment_name, username, class_folder, semester_folder))
                    row = cursor.fetchone()
                    assignment_id = row["id"] if row else None
                except Exception as e:
                    print(f"âŒ DB lookup failed for {f}: {e}")
                    assignment_id = None

                all_assignments[key].append({
                    "file_name": f,
                    "file_path": file_path,
                    "scene_id": None,
                    "individual_assignment_id": assignment_id
                })

    # 🖊️ Planning drawings — DB-backed (not filename-scanned), merged into
    # the same all_assignments shape the Sidebar already renders. Unlike
    # the video scan above there can be several current files per
    # individual_assignment_id, so page_order (not a filename regex) is
    # what keeps them in the right sequence.
    planning_rows = cursor.execute("""
        SELECT pf.id, pf.file_path, pf.file_name, pf.page_order,
               pf.individual_assignment_id,
               a.id AS assignment_id, a.name AS assignment_name,
               owner.name AS student_name,
               c.id AS class_id, c.class_name,
               s.year, s.term
        FROM planning_files pf
        JOIN individual_assignments ia ON pf.individual_assignment_id = ia.id
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN users owner ON ia.users_id = owner.id
        JOIN classes c ON a.class_id = c.id
        JOIN semesters s ON c.semester_id = s.id
        ORDER BY pf.individual_assignment_id, pf.page_order
    """).fetchall()

    # 🎥 Video references — also DB-backed, same merge point as planning
    # drawings. Unlike drawings these are reference material the instructor
    # views (not annotated/reviewed per-file) -- there's no per-file _R
    # lifecycle for these, so queue membership below is keyed off the
    # Planning step's own status instead.
    video_ref_rows = cursor.execute("""
        SELECT vr.id, vr.file_path, vr.file_name, vr.source_type, vr.external_url,
               vr.individual_assignment_id,
               a.id AS assignment_id, a.name AS assignment_name,
               owner.name AS student_name,
               c.id AS class_id, c.class_name, s.year, s.term
        FROM video_reference_files vr
        JOIN individual_assignments ia ON vr.individual_assignment_id = ia.id
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN users owner ON ia.users_id = owner.id
        JOIN classes c ON a.class_id = c.id
        JOIN semesters s ON c.semester_id = s.id
        ORDER BY vr.individual_assignment_id, vr.uploaded_at
    """).fetchall()

    # One shared "does this still need a look" signal for both drawings and
    # video references: show in the to-review queue while Planning is at
    # Submitted, drop out once it's Graded/Retake (an instructor decision),
    # and don't show at all before Submitted (In Progress/Needs Help are
    # still the student's work-in-progress, not something to review yet).
    planning_ia_ids = sorted({row["individual_assignment_id"] for row in planning_rows} |
                              {row["individual_assignment_id"] for row in video_ref_rows})
    planning_status_by_ia = {}
    if planning_ia_ids:
        placeholders = ",".join("?" * len(planning_ia_ids))
        status_rows = cursor.execute(f"""
            SELECT ias.individual_assignment_id, ias.current_status
            FROM individual_assignment_statuses ias
            JOIN steps s ON ias.step_id = s.id
            WHERE s.name = 'Planning' AND ias.individual_assignment_id IN ({placeholders})
        """, planning_ia_ids).fetchall()
        planning_status_by_ia = {r["individual_assignment_id"]: r["current_status"] for r in status_rows}

    def _planning_needs_review(ia_id):
        return (planning_status_by_ia.get(ia_id) or "").strip().lower() == "submitted"

    for row in planning_rows:
        key = f"{row['year']}-{row['term']} - {row['class_name']}"
        all_assignments.setdefault(key, [])
        all_assignments[key].append({
            "file_name": row["file_name"],
            "file_path": row["file_path"],
            "scene_id": None,
            "individual_assignment_id": row["individual_assignment_id"],
            "assignment_name": row["assignment_name"],
            "student_name": row["student_name"],
            "is_planning_drawing": True,
            "page_order": row["page_order"],
        })

        if _planning_needs_review(row["individual_assignment_id"]):
            assignments.append({
                "class_id": row["class_id"],
                "class_name": row["class_name"],
                "assignment_id": row["assignment_id"],
                "assignment_name": row["assignment_name"],
                "student_name": row["student_name"],
                "individual_assignment_id": row["individual_assignment_id"],
                "file_name": row["file_name"],
                "file_path": row["file_path"],
                "is_planning_drawing": True,
                "page_order": row["page_order"],
            })

    for row in video_ref_rows:
        key = f"{row['year']}-{row['term']} - {row['class_name']}"
        all_assignments.setdefault(key, [])
        if row["source_type"] == "upload":
            display_name = row["file_name"]
        else:
            # SideBar groups files by parsing "{assignment}_..." out of
            # file_name -- a raw URL won't parse that way, so link entries
            # get a synthetic name that follows the same convention.
            # external_url (below) is what's actually opened on click.
            display_name = f"{row['assignment_name']}_{row['student_name']}_PL_VideoRef_Link.url"
        entry = {
            "file_name": display_name,
            "file_path": row["file_path"],
            "scene_id": None,
            "individual_assignment_id": row["individual_assignment_id"],
            "assignment_name": row["assignment_name"],
            "student_name": row["student_name"],
            "is_video_reference": True,
            "source_type": row["source_type"],
            "external_url": row["external_url"],
        }
        all_assignments[key].append(entry)

        if _planning_needs_review(row["individual_assignment_id"]):
            assignments.append({
                **entry,
                "class_id": row["class_id"],
                "class_name": row["class_name"],
                "assignment_id": row["assignment_id"],
            })

    reviewed = films_raw.get("reviewed", {})
    to_review = films_raw.get("to_review", {})

    films_reviewed = [
        file
        for scenes in reviewed.values()
        for files in scenes.values()
        for file in files
    ]

    films_to_review = [
        file
        for scenes in to_review.values()
        for files in scenes.values()
        for file in files
    ]

    conn.close()

    return jsonify({
        "assignments": assignments,
        "films": films_to_review,
        "all_assignments": all_assignments,
        "all_films": all_films_data,
        "films_reviewed": films_reviewed
    })

@review_routes.route("/resolve_step_id", methods=["GET"])
def resolve_step_id():
    step_name = request.args.get("name", "").strip()
    if not step_name:
        return jsonify({"error": "Missing step name"}), 400

    conn = get_db()
    cursor = conn.cursor()
    row = cursor.execute("SELECT id FROM steps WHERE name = ?", (step_name,)).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": f"Step not found for name: {step_name}"}), 404

    return jsonify({"step_id": row["id"]})


# ----------------------------------------------------------------------------------------------------------------------
# GET FILES ASSIGNMENTS
# ----------------------------------------------------------------------------------------------------------------------

@review_routes.route("/get_assignment_status", methods=["GET"])
def get_assignment_status():
    """Return ALL grade step statuses for an individual assignment, including assignment & student names."""
    individual_assignment_id = request.args.get("id")

    if not individual_assignment_id:
        return jsonify({"error": "Missing individual_assignment_id"}), 400

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                ias.step_id,
                s.name AS step_name,
                ias.current_status,
                n.id AS node_id,
                a.name AS assignment_name,
                u.name AS student_name
            FROM individual_assignment_statuses ias
            JOIN steps s ON ias.step_id = s.id
            JOIN nodes n ON n.step_id = s.id
            JOIN individual_assignments ia ON ias.individual_assignment_id = ia.id
            JOIN assignments a ON ia.assignment_id = a.id
            JOIN users u ON ia.users_id = u.id
            WHERE s.name LIKE 'Grade%'
              AND ias.individual_assignment_id = ?
            ORDER BY ias.id ASC
        """, (individual_assignment_id,))

        rows = cursor.fetchall()
        if not rows:
            return jsonify({"error": "No grade steps found"}), 404

        # Pull assignment and student names from the first row (same for all)
        assignment_name = rows[0]["assignment_name"]
        student_name = rows[0]["student_name"]

        statuses = [
            {
                "step_id": row["step_id"],
                "step_name": row["step_name"],
                "status": row["current_status"],
                "node_id": row["node_id"]
            }
            for row in rows
        ]

        return jsonify({
            "assignment_name": assignment_name,
            "student_name": student_name,
            "statuses": statuses
        })

    except Exception as e:
        print("🔥 get_assignment_status error:", e)
        return jsonify({"error": "Server error", "details": str(e)}), 500
    finally:
        conn.close()

@review_routes.route("/get_grade_options", methods=["GET"])
def get_grade_options():
    """
    Fetch grade options either by a single step_id (returns a flat array
    of {name, color} -- used by the film/scene review panel, which
    already knows each status's step_id), or by assignment_id (an
    individual_assignments.id -- used by the Assignment review panel,
    markup/page.jsx's fetch(`.../get_grade_options?assignment_id=...`),
    which only has the assignment, not a step_id up front). The
    assignment_id branch returns every Grade-* step under that
    assignment's workflow as [{step_id, options: [...]}, ...], since an
    assignment can have more than one (e.g. Grade-Blocking, Grade-Polish)
    -- that shape is exactly what page.jsx's
    `data.forEach(step => optionsByStep[step.step_id] = step.options)`
    expects. Previously this endpoint only ever read step_id, so the
    assignment_id call always 400'd and every assignment's grade dropdown
    stayed empty/disabled.
    """
    step_id = request.args.get("step_id")
    individual_assignment_id = request.args.get("assignment_id")

    conn = get_db()
    cursor = conn.cursor()

    def fetch_options(sid):
        cursor.execute("""
            SELECT name, color,
                CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INTEGER) AS y_value
            FROM nodes
            WHERE step_id = ?
            ORDER BY y_value ASC
        """, (sid,))
        return [{"name": r["name"], "color": r["color"]} for r in cursor.fetchall()]

    if individual_assignment_id:
        row = cursor.execute("""
            SELECT a.parent_step_id
            FROM individual_assignments ia
            JOIN assignments a ON a.id = ia.assignment_id
            WHERE ia.id = ?
        """, (individual_assignment_id,)).fetchone()

        if not row or not row["parent_step_id"]:
            conn.close()
            return jsonify([])

        grade_steps = cursor.execute("""
            SELECT id FROM steps WHERE parent_id = ? AND name LIKE 'Grade%'
        """, (row["parent_step_id"],)).fetchall()

        result = [{"step_id": s["id"], "options": fetch_options(s["id"])} for s in grade_steps]
        conn.close()
        return jsonify(result)

    if not step_id:
        conn.close()
        return jsonify({"error": "Missing step_id or assignment_id"}), 400

    options = fetch_options(step_id)
    conn.close()

    if not options:
        return jsonify({"error": "No grades available"}), 404

    return jsonify(options)

@review_routes.route("/api/graded_assignments_with_files", methods=["GET"])
@login_required
def get_graded_assignments_with_files():
    user_name = session.get("username")
    user_id = session.get("user_id")

    if not user_name or not user_id:
        return jsonify([])

    conn = get_db()
    cursor = conn.cursor()

    query = """
        SELECT c.class_name, a.name AS assignment_name, ia.id AS individual_assignment_id,
            ias.current_status AS grade
        FROM individual_assignments ia
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN classes c ON a.class_id = c.id
        JOIN individual_assignment_statuses ias ON ia.id = ias.individual_assignment_id
        JOIN steps s ON ias.step_id = s.id
        WHERE ia.users_id = ? AND s.name LIKE 'Grade%'
        ORDER BY ias.id DESC
    """

    rows = cursor.execute(query, (user_id,)).fetchall()
    results = []

    for row in rows:
        class_name = row["class_name"]
        assignment_name = row["assignment_name"]
        grade = row["grade"]
        individual_assignment_id = row["individual_assignment_id"]
        semester_row = cursor.execute("""
            SELECT s.year, s.term
            FROM classes c
            JOIN semesters s ON c.semester_id = s.id
            WHERE c.class_name = ?
        """, (class_name,)).fetchone()

        if not semester_row:
            continue

        semester_folder = f"{semester_row['year']}-{semester_row['term']}"
        class_path = os.path.join(BASE_VIDEO_DIR, semester_folder, class_name, "Assignments")


        if not os.path.exists(class_path):
            continue

        reviewed_files = [f for f in os.listdir(class_path)
                        if f.startswith(f"{assignment_name}_{user_name}_v") and f.endswith("_R.webm")]
        
        if not reviewed_files:
            continue

        reviewed_files.sort(reverse=True)
        file_path = os.path.join(class_path, reviewed_files[0])

        results.append({
            "class_name": class_name,
            "assignment_name": assignment_name,
            "grade": grade,
            "file_path": file_path
        })


    return jsonify(results)

# ----------------------------------------------------------------------------------------------------------------------
# GET FILES FILMS
# ----------------------------------------------------------------------------------------------------------------------
@review_routes.route("/films", methods=["GET"])
def get_all_films():

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, name
            FROM films
            ORDER BY name COLLATE NOCASE
        """)
        rows = cursor.fetchall()
        return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])

    except Exception as e:
        print(f"❌ Failed to fetch films: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()

@review_routes.route("/films/scenes", methods=["GET"])
def get_all_scenes():

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, scene_number FROM scenes ORDER BY scene_number")
        rows = cursor.fetchall()
        scenes = [{"id": r["id"], "scene_number": str(r["scene_number"]).zfill(3)} for r in rows]
        return jsonify(scenes)
    finally:
        conn.close()

@review_routes.route("/films/<int:film_id>/scenes", methods=["GET"])
def get_scenes_for_film(film_id):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, scene_number, description
            FROM scenes
            WHERE film_id = ?
            ORDER BY scene_number
        """, (film_id,))
        rows = cursor.fetchall()
        scenes = [
            {
                "id": r["id"],
                "scene_number": str(r["scene_number"]).zfill(3),
                "description": r["description"]
            }
            for r in rows
        ]
        return jsonify(scenes)
    except Exception as e:
        print(f"❌ Failed to fetch scenes for film_id={film_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@review_routes.route("/films/scenes/<int:scene_id>/shots", methods=["GET"])
def get_scene_shots(scene_id):
    """
    Returns all shots for a scene AND (optionally) resolves the latest .webm per shot
    for the given STEP (e.g., LAY) by scanning the file system.

    Query params:
      - step: required to resolve files (e.g., LAY, ANIM). If omitted, file_path will be null.
    """
    import os, re, glob
    from flask import request, jsonify

    step = (request.args.get("step") or "").strip()
    step = step.upper() if step else ""  # normalize like LAY, ANIM, etc.

    conn = get_db()
    cursor = conn.cursor()

    try:
        # 1) Get scene info (scene_number + film_name)
        cursor.execute("""
            SELECT s.scene_number, f.name AS film_name
            FROM scenes s
            JOIN films f ON f.id = s.film_id
            WHERE s.id = ?
        """, (scene_id,))
        row_scene = cursor.fetchone()
        if not row_scene:
            return jsonify({"error": f"Scene not found: {scene_id}"}), 404

        scene_number = str(row_scene["scene_number"]).zfill(3)
        film_name = row_scene["film_name"]

        # 2) Get shots for the scene (as you already had)
        cursor.execute("""
            SELECT id, shot_number, scene_id
            FROM shots
            WHERE scene_id = ?
            ORDER BY shot_number
        """, (scene_id,))
        rows = cursor.fetchall()

        # 3) If a step is provided, try to resolve a latest version per shot from disk
        base_scene_dir = os.path.join(r"\\GAAAP1PRD01W\Films", film_name, scene_number)

        results = []
        for r in rows:
            shot_num = str(r["shot_number"]).zfill(3)

            resolved_file_path = None
            resolved_file_name = None

            if step:
                # Shot folder pattern(s)
                shot_dir_1 = os.path.join(base_scene_dir, shot_num)            # e.g. \Films\testme\010\040
                shot_dir_2 = os.path.join(base_scene_dir, f"{scene_number}_{shot_num}")  # fallback pattern

                # Candidate folders (prefer \scene\shot)
                candidate_dirs = [shot_dir_1, shot_dir_2]

                # Build glob pattern for files like:
                # testme_010_040_LAY_*.webm   (we’ll pick highest _v##)
                pattern_name = f"{film_name}_{scene_number}_{shot_num}_{step}_*.webm"

                best_path = None
                best_v = -1
                best_mtime = 0.0

                for d in candidate_dirs:
                    if not os.path.isdir(d):
                        continue
                    pattern = os.path.join(d, pattern_name)
                    files = glob.glob(pattern)
                    for fp in files:
                        bn = os.path.basename(fp)
                        m = re.search(r"_v(\d+)", bn, re.IGNORECASE)
                        v = int(m.group(1)) if m else -1
                        mtime = os.path.getmtime(fp)
                        # pick highest v; if tie, newest mtime
                        if (v, mtime) > (best_v, best_mtime):
                            best_v, best_mtime, best_path = v, mtime, fp

                if best_path:
                    resolved_file_path = os.path.normpath(best_path)
                    resolved_file_name = os.path.basename(best_path)

            results.append({
                "id": r["id"],
                "shot_number": shot_num,
                "scene_id": r["scene_id"],
                "film_name": film_name,
                "scene_number": scene_number,
                "step": step,
                "file_name": resolved_file_name,
                "file_path": resolved_file_path,  # can be None if not found or step omitted
            })

        return jsonify(results)

    except Exception as e:
        print("❌ Failed to fetch shots:", e)
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()

@review_routes.route('/get_scene_status', methods=["GET"])
def get_scene_status():
    print("🚀 get_scene_status() route executing!")

    scene_id = request.args.get("scene_id", type=int)
    file_name = request.args.get("file_name", type=str)
    is_sb = request.args.get("is_sb", default=False, type=lambda v: v.lower() == "true")

    conn = get_db()
    cursor = conn.cursor()

    try:
        step_name_guess = "Thumbnails"
        if file_name:
            # More flexible match: works with "_LAY_", "_LAY", or "_LAY_Little"
            step_match = re.search(r"_([A-Za-z]+)(?:_|$)", file_name)
            print(f"🧠 DEBUG: Step match = {step_match.group(1) if step_match else 'None'} from file_name = {file_name}")

            step_name_guess = "Thumbnails"  # default fallback
            if step_match:
                code = step_match.group(1).upper()
                # Layout -> Blocking -> Animation -> Lighting are each their
                # own top-level department code now (BL is no longer a
                # sub-step suffix on ANIM -- see GAAPlayblastTool_V7.py).
                step_map = {
                    "THUMB": "Thumbnails",
                    "SB": "Storyboards",
                    "LAY": "Layout",
                    "BL": "Blocking",
                    "ANIM": "Animation",
                    "LGT": "Lighting"
                }
                step_name_guess = step_map.get(code, "Thumbnails")

            step_name_full = f"FB {step_name_guess}"
            print(f"🧠 DEBUG: step_name_guess = {step_name_guess}")
            print(f"🧠 DEBUG: step_name_full = {step_name_full}")

        # --------------------------------------------------
        # SHORT-CIRCUIT FOR REVIEWED THUMB / SB FILES
        # --------------------------------------------------
        if file_name and re.search(r"_(THUMB|SB)_v\d+_R\.", file_name, re.IGNORECASE):
            print("🛑 SHORT-CIRCUIT: Reviewed THUMB/SB file — skipping shot logic")

            return jsonify({
                "scene_id": scene_id,
                "step_code": step_name_guess,
                "step_name": step_name_full,
                "status": "reviewed",
                "options": []
            })



        # 🧠 SCENE LOOKUP BY FILENAME
        if not scene_id and file_name:
            print("🧩 DEBUG: Scene lookup starting...")
            print(f"🧩 DEBUG: Incoming file_name = '{file_name}'")

            # ---- Extract 3-digit scene number ----
            match = re.search(r"_(\d{3})_", file_name)
            scene_number = match.group(1) if match else None
            print(f"🧩 DEBUG: Parsed scene_number = '{scene_number}'")

            # ---- Film guess (before first underscore) ----
            film_guess = file_name.split("_")[0].lower().strip()
            print(f"🧩 DEBUG: Film guess = '{film_guess}'")

            # ---- Dump all films/scenes in DB ----
            cursor.execute("SELECT f.name AS film, s.scene_number AS scene FROM films f JOIN scenes s ON f.id = s.film_id")
            all_rows = cursor.fetchall()
            print("🧩 DEBUG: Films/scenes currently in DB:")
            for r in all_rows:
                print(f"      film='{r['film']}', scene='{r['scene']}'")

            # ---- Run the cleaned query ----
            if scene_number:
                print(f"🧩 DEBUG: Executing lookup with film_guess='{film_guess}' scene_number='{scene_number}'")
                cursor.execute("""
                    SELECT s.id AS scene_id, f.name AS film_name, s.scene_number
                    FROM scenes s
                    JOIN films f ON f.id = s.film_id
                    WHERE TRIM(LOWER(REPLACE(f.name, ' ', ''))) = TRIM(LOWER(?))
                    AND TRIM(s.scene_number) = TRIM(?)
                    LIMIT 1
                """, (film_guess, scene_number))

                row = cursor.fetchone()
                print(f"🧩 DEBUG: SQL returned → {row}")
                if row:
                    scene_id = row["scene_id"]
                    print(f"✅ SUCCESS: Found scene_id={scene_id} (film='{row['film_name']}', scene='{row['scene_number']}')")
                else:
                    print("❌ DEBUG: No DB match found for that film/scene combination.")
            else:
                print("❌ DEBUG: No 3-digit scene number found in filename.")


        if not scene_id:
            return jsonify({"error": "Missing or invalid scene_id"}), 400

        cursor.execute("""
            SELECT f.step_id
            FROM scenes s
            JOIN films f ON s.film_id = f.id
            WHERE s.id = ?
        """, (scene_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Scene not found"}), 404

        parent_step_id = row["step_id"]

        step_name_full = f"FB {step_name_guess}"
        # Layout, Blocking, Animation, and Lighting are each per-shot steps
        # tracked in shot_step_assignments -- must be included here or the
        # query below silently falls through to scene_progress_steps
        # instead, finding nothing for a shot-level step.
        uses_shots_table = step_name_guess in [
            "Storyboards", "Layout", "Blocking", "Animation", "Lighting"
        ]

        # Per-shot files (Film_Scene_Shot_STEP_User_v#) carry a SECOND
        # 3-digit group after the scene number -- scene-level files
        # (THUMB/SB) only ever have one, so this simply won't match for
        # those and the query below falls back to scene-wide, same as
        # before. Without this, a scene with more than one shot returns
        # whichever shot's row LIMIT 1 happens to grab first (lowest
        # shot_id), not the shot the file actually belongs to -- e.g. a
        # scene where shot 010 is already "Approved" made every OTHER
        # shot in that scene show "Approved" too.
        shot_number = None
        if file_name:
            shot_num_match = re.search(r"_\d{3}_(\d{3})_", file_name)
            shot_number = shot_num_match.group(1) if shot_num_match else None
            print(f"🧠 DEBUG: Parsed shot_number = {shot_number}")

        if uses_shots_table and shot_number:
            cursor.execute("""
                SELECT ssa.step_id, ssa.status, st.name
                FROM shot_step_assignments ssa
                JOIN shots sh ON ssa.shot_id = sh.id
                JOIN steps st ON ssa.step_id = st.id
                WHERE sh.scene_id = ?
                AND CAST(sh.shot_number AS INTEGER) = CAST(? AS INTEGER)
                AND st.name = ?
                AND st.parent_id = ?
                LIMIT 1
            """, (scene_id, shot_number, step_name_full, parent_step_id))
        elif uses_shots_table:
            cursor.execute("""
                SELECT ssa.step_id, ssa.status, st.name
                FROM shot_step_assignments ssa
                JOIN shots sh ON ssa.shot_id = sh.id
                JOIN steps st ON ssa.step_id = st.id
                WHERE sh.scene_id = ?
                AND st.name = ?
                AND st.parent_id = ?
                LIMIT 1
            """, (scene_id, step_name_full, parent_step_id))
        else:
            cursor.execute("""
                SELECT sps.step_id, sps.status, st.name
                FROM scene_progress_steps sps
                JOIN steps st ON sps.step_id = st.id
                WHERE sps.scene_id = ?
                AND st.name = ?
                AND st.parent_id = ?
                LIMIT 1
            """, (scene_id, step_name_full, parent_step_id))


        step = cursor.fetchone()
        if not step:
            return jsonify({"error": f"No matching grading step found for '{step_name_guess}'"}), 404

        # 🧠 If this is an FB step, find its paired non-FB version (e.g., "Layout")
        display_step_id = step["step_id"]
        update_step_id = step["step_id"]
        display_name = step["name"]
        display_status = step["status"]

        if display_name.startswith("FB "):
            paired_name = display_name.replace("FB ", "", 1).strip()
            cursor.execute(
                "SELECT id FROM steps WHERE name = ? AND parent_id = ? LIMIT 1",
                (paired_name, parent_step_id)
            )
            paired = cursor.fetchone()
            if paired:
                print(f"🔄 Swapping update target → FB '{display_name}' will update '{paired_name}' (id={paired['id']})")
                update_step_id = paired["id"]
            else:
                print(f"⚠️ No paired step found for '{display_name}'")

        print(f"🧩 Returning display_step_id={display_step_id}, update_step_id={update_step_id}, name={display_name}")

        return jsonify({
            "display_step_id": display_step_id,   # e.g. 249 (FB Layout)
            "update_step_id": update_step_id,     # e.g. 248 (Layout)
            "step_name": display_name,
            "status": display_status,
            "options": []
        })


    except Exception as e:
        import traceback
        print("Get_scene_status() failed:", e)
        traceback.print_exc()
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()

@review_routes.route("/get_shot_step_status", methods=["GET"])
def get_shot_step_status():
    scene_num = request.args.get("scene")
    shot_num = request.args.get("shot")
    step_id = request.args.get("step_id", type=int)

    if not scene_num or not shot_num or not step_id:
        return jsonify({"error": "Missing scene, shot or step_id"}), 400

    conn = get_db()
    cursor = conn.cursor()

    try:
        shot_row = cursor.execute("""
            SELECT sh.id
            FROM shots sh
            JOIN scenes s ON sh.scene_id = s.id
            WHERE s.scene_number = ? AND sh.shot_number = ?
        """, (scene_num, shot_num)).fetchone()

        if not shot_row:
            return jsonify({"error": "Shot not found"}), 404

        shot_id = shot_row["id"]

        row = cursor.execute("""
            SELECT status
            FROM shot_step_assignments
            WHERE shot_id = ? AND step_id = ?
        """, (shot_id, step_id)).fetchone()

        if not row:
            return jsonify({"error": "No step status found"}), 404

        return jsonify({"status": row["status"]})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@review_routes.route("/get_feedback_status/<scene_id>/<step_code>", methods=["GET"])
def get_feedback_status(scene_id, step_code):
    """
    Returns:
      - feedback_step_id      -> the FB version of the step
      - statuses[]            -> one row per shot in scene
      - options[]             -> dropdown list for FB step
    """
    print(f"🧩 get_feedback_status(): scene_id={scene_id}, step_code={step_code}")

    conn = get_db()
    cur = conn.cursor()

    try:
        step_code = step_code.upper()

        # --------------------------------------------------
        # SHORT-CIRCUIT FOR THUMB / SB (scene-level steps)
        # --------------------------------------------------
        if step_code in ("SB", "THUMB", "THB"):
            print("🛑 SHORT-CIRCUIT: Scene-level SB/THUMB — skipping shot feedback logic")

            base_step_name = "Storyboards" if step_code == "SB" else "Thumbnails"
            fb_step_name = f"FB {base_step_name}"

            cur.execute("SELECT id FROM steps WHERE name = ?", (fb_step_name,))
            fb_row = cur.fetchone()
            fb_step_id = fb_row["id"] if fb_row else None

            return jsonify({
                "feedback_step": fb_step_name,
                "feedback_step_id": fb_step_id,
                "statuses": [],
                "options": []
            })

        # --------------------------------------------------
        # NORMAL SHOT-BASED FEEDBACK FLOW
        # --------------------------------------------------

        # 1️⃣ Resolve scene by ID or scene number
        cur.execute("""
            SELECT id, scene_number
            FROM scenes
            WHERE id = ? OR scene_number = ?
        """, (scene_id, scene_id))
        scene_row = cur.fetchone()
        if not scene_row:
            return jsonify({"error": "Scene not found"}), 404

        scene_id = scene_row["id"]
        print(f"🎯 Resolved scene ID → {scene_id}")

        # 2️⃣ Map shorthand codes to real step names
        step_map = {
            "SB": "Storyboards",
            "THB": "Thumbnails",
            "LAY": "Layout",
            "ANIM": "Animation",
            "LGT": "Lighting"
        }

        base_step_name = step_map.get(step_code)
        if not base_step_name:
            return jsonify({"error": f"Unrecognized step_code {step_code}"}), 400

        print(f"🎯 Base step name resolved → {base_step_name}")

        # 3️⃣ Find FB step
        fb_step_name = f"FB {base_step_name}"
        cur.execute("SELECT id FROM steps WHERE name = ?", (fb_step_name,))
        fb_row = cur.fetchone()
        fb_step_id = fb_row["id"] if fb_row else None

        if not fb_step_id:
            return jsonify({"error": f"FB step not found for {base_step_name}"}), 404

        print(f"🧠 Using FB step → {fb_step_name} (id={fb_step_id})")

        # 4️⃣ Get all shots in this scene
        cur.execute("SELECT id, shot_number FROM shots WHERE scene_id = ?", (scene_id,))
        shots = cur.fetchall()

        results = []
        for shot in shots:
            cur.execute("""
                SELECT status
                FROM shot_step_assignments
                WHERE shot_id = ? AND step_id = ?
            """, (shot["id"], fb_step_id))
            row = cur.fetchone()

            results.append({
                "shot_id": shot["id"],
                "shot_number": shot["shot_number"],
                "status": row["status"] if row else "Submitted",
                "step_id": fb_step_id
            })

        # 5️⃣ Fetch dropdown options
        cur.execute("""
            SELECT id, name, color, position
            FROM nodes
            WHERE step_id = ?
            ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INTEGER)
        """, (fb_step_id,))
        node_rows = cur.fetchall()

        options = [{
            "node_id": r["id"],
            "status": r["name"],
            "color": r["color"],
            "position": r["position"]
        } for r in node_rows]

        return jsonify({
            "feedback_step": fb_step_name,
            "feedback_step_id": fb_step_id,
            "statuses": results,
            "options": options
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()


@review_routes.route("/films/<int:film_id>/steps", methods=["GET"])
def get_steps_for_film(film_id):

    conn = get_db()
    cursor = conn.cursor()

    try:
        # 1️⃣ Find the film's starting step_id (flow root)
        cursor.execute("SELECT step_id FROM films WHERE id = ?", (film_id,))
        film_row = cursor.fetchone()
        if not film_row:
            return jsonify({"error": f"No film found with id={film_id}"}), 404

        root_step_id = film_row["step_id"]

        # 2️⃣ Find all steps that belong to that flow (children of root)
        cursor.execute("""
            SELECT id, name AS step_name, short_code
            FROM steps
            WHERE parent_id = ?
              AND (short_code IS NOT NULL AND short_code != 'THB')
            ORDER BY id
        """, (root_step_id,))

        rows = cursor.fetchall()
        result = [
            {"id": row["id"], "step_name": row["step_name"], "short_code": row["short_code"]}
            for row in rows
        ]

        return jsonify(result)

    except Exception as e:
        print(f"❌ Failed to fetch steps for film {film_id}: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()

# ----------------------------------------------------------------------------------------------------------------------
# UPLOAD/LOAD
# ----------------------------------------------------------------------------------------------------------------------

@review_routes.route("/upload_assignment", methods=["POST"])
@login_required
def upload_assignment():
    try:
        file = request.files.get("file")
        assignment_id = request.form.get("assignment_id")
        assignment_name = request.form.get("assignment_name")
        class_name = request.form.get("class_name")
        user_name = session.get("username")

        if not all([file, assignment_id, assignment_name, class_name, user_name]):
            return jsonify({"error": "Missing required fields"}), 400

        conn = get_db()
        cursor = conn.cursor()
        semester_row = cursor.execute("""
            SELECT s.year, s.term
            FROM classes c
            JOIN semesters s ON c.semester_id = s.id
            WHERE c.class_name = ?
        """, (class_name,)).fetchone()

        if not semester_row:
            return jsonify({"error": "Semester not found for class"}), 400

        semester_folder = f"{semester_row['year']}-{semester_row['term']}"
        base_dir = os.path.join(BASE_VIDEO_DIR, semester_folder, class_name, "Assignments")

        os.makedirs(base_dir, exist_ok=True)

        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".webm", ".png"]:
            return jsonify({"error": "Unsupported file type"}), 400

        existing_files = [f for f in os.listdir(base_dir)
                          if f.startswith(f"{assignment_name}_{user_name}_v") and f.endswith(ext)]
        versions = [int(re.search(r"_v(\\d+)", f).group(1))
                    for f in existing_files if re.search(r"_v(\\d+)", f)]
        next_version = max(versions, default=0) + 1

        new_filename = f"{assignment_name}_{user_name}_v{next_version}{ext}"
        filepath = os.path.join(base_dir, new_filename)
        file.save(filepath)

        conn = get_db()
        conn.execute("""
            UPDATE individual_assignment_statuses
            SET current_status = 'Submitted'
            WHERE individual_assignment_id = ?
            AND step_id IN (SELECT id FROM steps WHERE name LIKE 'Assignment%')
        """, (assignment_id,))
        conn.commit()
        conn.close()

        return jsonify({"message": "Uploaded successfully", "file_name": new_filename})

    except Exception as e:
        print(f"ðŸ”¥ Upload Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@review_routes.route("/maya-submit", methods=["POST"])
def maya_submit():
    try:
        # --- Validate secret key ---
        secret = request.form.get("secret")
        if secret != os.environ.get("MAYA_SUBMIT_SECRET", "DAAP_CAMP_2026"):
            return jsonify({"error": "Unauthorized"}), 403

        file          = request.files.get("file")
        assignment_name = request.form.get("assignment_name")
        class_name    = request.form.get("class_name")
        user_name     = request.form.get("user_name")  # from Maya dropdown, not session

        if not all([file, assignment_name, class_name, user_name]):
            return jsonify({"error": "Missing required fields"}), 400

        conn = get_db()
        cursor = conn.cursor()

        # --- Get semester folder ---
        semester_row = cursor.execute("""
            SELECT s.year, s.term
            FROM classes c
            JOIN semesters s ON c.semester_id = s.id
            WHERE c.class_name = ?
        """, (class_name,)).fetchone()

        if not semester_row:
            return jsonify({"error": f"Semester not found for class: {class_name}"}), 400

        semester_folder = f"{semester_row['year']}-{semester_row['term']}"
        base_dir = os.path.join(BASE_VIDEO_DIR, semester_folder, class_name, "Assignments")
        os.makedirs(base_dir, exist_ok=True)

        # --- Validate file type ---
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".webm", ".png"]:
            return jsonify({"error": "Unsupported file type"}), 400

        # --- Version the file ---
        existing_files = [f for f in os.listdir(base_dir)
                          if f.startswith(f"{assignment_name}_{user_name}_v") and f.endswith(ext)]
        versions = [int(re.search(r"_v(\d+)", f).group(1))
                    for f in existing_files if re.search(r"_v(\d+)", f)]
        next_version = max(versions, default=0) + 1

        new_filename = f"{assignment_name}_{user_name}_v{next_version}{ext}"
        filepath = os.path.join(base_dir, new_filename)
        file.save(filepath)

        # --- Look up individual_assignment_id ---
        ia_row = cursor.execute("""
            SELECT ia.id
            FROM individual_assignments ia
            JOIN assignments a ON ia.assignment_id = a.id
            JOIN classes c ON a.class_id = c.id
            JOIN users u ON ia.users_id = u.id
            WHERE a.name = ? AND c.class_name = ? AND u.name = ?
            LIMIT 1
        """, (assignment_name, class_name, user_name)).fetchone()

        if not ia_row:
            return jsonify({"error": f"No assignment found for {user_name} / {assignment_name} in {class_name}"}), 404

        # --- Update status to Submitted ---
        conn.execute("""
            UPDATE individual_assignment_statuses
            SET current_status = 'Submitted'
            WHERE individual_assignment_id = ?
            AND step_id IN (SELECT id FROM steps WHERE name LIKE 'Assignment%')
        """, (ia_row["id"],))
        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "message": f"Submitted successfully",
            "file_name": new_filename
        })

    except Exception as e:
        print(f"🔥 Maya Submit Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@review_routes.route('/upload_film_shot', methods=['POST'])
def upload_film_shot():
    conn = get_db()
    cur = conn.cursor()

    film_name = request.form.get('film_name')
    scene_number = request.form.get('scene_number')
    shot_number = request.form.get('shot_number')
    step_id = int(request.form.get('step_id'))

    file = request.files.get('file')
    if not file:
        return jsonify({"error": "Missing file"}), 400

    # 🔹 Step 1: Find the shot
    shot_row = cur.execute("""
        SELECT sh.id AS shot_id
        FROM shots sh
        JOIN scenes s ON s.id = sh.scene_id
        JOIN films f ON f.id = s.film_id
        WHERE f.name = ? AND s.scene_number = ? AND sh.shot_number = ?
        LIMIT 1
    """, (film_name, scene_number, shot_number)).fetchone()

    if not shot_row:
        conn.close()
        return jsonify({"error": "Shot not found"}), 404

    shot_id = shot_row["shot_id"]

    # 🔹 Step 2: Determine paired production step (non-FB)
    # Resolved by name (strip "FB " prefix, look up the sibling step under
    # the same parent) rather than assuming FB step_id == production
    # step_id + 1 -- that held for Layout (248/249) and Animation
    # (251/252) in this film's workflow, but NOT for Lighting (253/274),
    # where it silently pointed at a step_id (273) that doesn't exist,
    # so the UPDATE below matched zero rows and Lighting submissions never
    # actually flipped to "Submitted".
    fb_step_row = cur.execute(
        "SELECT name, parent_id FROM steps WHERE id = ?", (step_id,)
    ).fetchone()
    if not fb_step_row:
        conn.close()
        return jsonify({"error": f"step_id {step_id} not found"}), 404

    production_name = fb_step_row["name"]
    if production_name.startswith("FB "):
        production_name = production_name[len("FB "):]

    production_step_row = cur.execute(
        "SELECT id FROM steps WHERE name = ? AND parent_id = ?",
        (production_name, fb_step_row["parent_id"])
    ).fetchone()
    if not production_step_row:
        conn.close()
        return jsonify({"error": f"No paired production step found for '{fb_step_row['name']}'"}), 404

    update_step_id = production_step_row["id"]  # this pattern holds across your pipeline

    # 🔹 Step 3: Save playblast
    save_path = f"//GAAAP1PRD01W/Films/{film_name}/{scene_number}/{shot_number}/{file.filename}"
    file.save(save_path)

    # 🔹 Step 4: Mark production step (Layout) as Submitted
    cur.execute("""
        UPDATE shot_step_assignments
        SET status = 'Submitted'
        WHERE shot_id = ? AND step_id = ?
    """, (shot_id, update_step_id))
    logger.info(f"[UPLOAD] Set Layout step {update_step_id} → Submitted for shot {shot_id}")

    # 🔹 Step 5: Trigger crossflow (Submitted → FB Layout: In Approvals)
    node_row = cur.execute("""
        SELECT id FROM nodes WHERE name = 'Submitted' AND step_id = ?
    """, (update_step_id,)).fetchone()

    if node_row:
        parent_node_id = node_row["id"]
        links = cur.execute("""
            SELECT child_node_id, to_flow_id
            FROM links
            WHERE parent_node_id = ?
        """, (parent_node_id,)).fetchall()

        for link in links:
            child_node = cur.execute(
                "SELECT name FROM nodes WHERE id = ?",
                (link["child_node_id"],)
            ).fetchone()
            if not child_node:
                continue

            target_step_id = link["to_flow_id"]
            target_status = child_node["name"]

            cur.execute("""
                UPDATE shot_step_assignments
                SET status = ?
                WHERE shot_id = ? AND step_id = ?
            """, (target_status, shot_id, target_step_id))
            logger.info(f"[CROSSFLOW] Layout (Submitted) → FB Layout ({target_status})")

    conn.commit()
    conn.close()

    return jsonify({
        "file_path": save_path,
        "message": "Film shot uploaded and marked Submitted.",
        "shot_id": shot_id,
        "step_id": update_step_id
    })

@review_routes.route("/load_json", methods=["GET"])
def load_annotation_json():

    file_path = request.args.get("path")
    if not file_path or not os.path.isfile(file_path):
        return jsonify({})

    try:
        with open(file_path, "r") as f:
            data = json.load(f)
        response = make_response(jsonify(data))
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response
    except Exception as e:
        print("âŒ JSON Load Error:", e)
        return jsonify({})


@review_routes.route("/get_previous_version", methods=["POST"])
def get_previous_version():
    data = request.json
    current_path = data.get("file_path")

    if not current_path or not os.path.exists(current_path):
        return jsonify({"success": False})

    directory = os.path.dirname(current_path)
    filename = os.path.basename(current_path)

    match = re.match(r"(.*)_v(\d+)(_R)?(\.\w+)", filename)
    if not match:
        return jsonify({"success": False})

    base_name = match.group(1)
    current_version = int(match.group(2))
    extension = match.group(4)

    versions = []

    for f in os.listdir(directory):
        m = re.match(rf"{re.escape(base_name)}_v(\d+)(_R)?{re.escape(extension)}", f)
        if m:
            v = int(m.group(1))
            if v < current_version:
                versions.append(v)

    if not versions:
        return jsonify({"success": False})

    previous_version = max(versions)
    previous_file = os.path.join(directory, f"{base_name}_v{previous_version}{extension}")

    return jsonify({
        "success": True,
        "previous_path": previous_file
    })


@review_routes.route("/list_versions", methods=["GET"])
def list_versions():
    """
    Lists prior REVIEWED versions of the same shot as file_path -- "reviewed"
    meaning a _v{N}_R.<ext> video exists, since that's the signal a grader
    actually looked at it (e.g. "The Blinker_v1_R.webm" while the artist is
    now on "The Blinker_v2.webm"). Matched on the video file rather than the
    _R.json sidecar: save_reviewed always writes a json alongside the
    renamed video, but requiring it here would silently drop any version
    reviewed through a path that didn't (or whose json got lost/moved) --
    a version with a video but no strokes drawn should still show up in
    the compare list, just with nothing to ghost.
    """
    current_path = request.args.get("file_path", "")
    if not current_path:
        return jsonify({"versions": []})

    directory = os.path.dirname(current_path)
    filename = os.path.basename(current_path)

    match = re.match(r"(.*)_v(\d+)(_R)?(\.\w+)", filename)
    if not match or not os.path.isdir(directory):
        return jsonify({"versions": []})

    base_name = match.group(1)
    current_version = int(match.group(2))
    extension = match.group(4)

    versions = []
    for f in os.listdir(directory):
        m = re.match(rf"{re.escape(base_name)}_v(\d+)_R{re.escape(extension)}$", f, re.IGNORECASE)
        if m:
            v = int(m.group(1))
            if v == current_version:
                continue
            json_path = os.path.join(directory, f"{base_name}_v{v}_R.json")
            versions.append({
                "version": v,
                "json_path": json_path,
                "video_path": os.path.join(directory, f),
                "has_annotations": os.path.exists(json_path)
            })

    versions.sort(key=lambda x: x["version"], reverse=True)
    return jsonify({"versions": versions})

# ----------------------------------------------------------------------------------------------------------------------
# SAVE FILES
# ----------------------------------------------------------------------------------------------------------------------


@review_routes.route("/save_reviewed", methods=["POST"])
def save_reviewed():
    """
    Accepts ANY of the following payload shapes:
      - {"folder": "...", "pattern": "film_scene_shot_step_*.webm", "annotations": {...}}
      - {"target_dir": "...", "base_glob": "film_scene_shot_step_*.webm"}
      - {"file_path": "\\\\…\\film_scene_shot_step_*.webm"}  <-- UI sends this

    Finds latest *_v#.webm → renames to *_v#_R.webm and writes *_v#_R.json.
    Emits trace logs: SAV4..SAV7.
    """

    raw = request.get_json(silent=True) or {}
    print("🎯 FAVORITE FLAG RECEIVED:", raw.get("favorite"))

    favorite = raw.get("favorite", False)

    # tolerant key resolution
    target_dir = (raw.get("target_dir") or raw.get("review_folder") or raw.get("folder") or "").strip()
    base_glob  = (raw.get("base_glob")  or raw.get("base_name")      or raw.get("pattern") or "").strip()

    # handle file_path directly
    file_path = (raw.get("file_path") or raw.get("path") or "").strip()
    if (not target_dir or not base_glob) and file_path:
        norm = os.path.normpath(file_path)
        target_dir = os.path.dirname(norm)
        base_glob  = os.path.basename(norm)

    target_dir = target_dir.replace("/", os.sep)

    if not target_dir or not base_glob:
        return jsonify_safe({"stage": "recv", "error": "Missing folder/pattern", "received": raw}, 400)
    if not os.path.isdir(target_dir):
        return jsonify_safe({"stage": "dir_check", "error": "Directory not found", "target_dir": target_dir}, 404)

    # generalize if single filename
    if base_glob.lower().endswith(".webm") and "*" not in base_glob:
        base_glob = re.sub(r"_v\d+.*\.webm$", "_*.webm", base_glob, flags=re.IGNORECASE)
        base_glob = re.sub(r"_R\.webm$", "_*.webm", base_glob, flags=re.IGNORECASE)

    # ensure version pattern
    pattern = base_glob
    if "_v" not in pattern:
        if pattern.lower().endswith(".webm"):
            pattern = pattern[:-5]
        pattern = f"{pattern}_v*.webm"

    full_glob = os.path.join(target_dir, pattern)

    # ---- SAV5: find candidate ------------------------------------------------
    candidates = glob.glob(full_glob)
    # filter out already reviewed files (_R)
    non_reviewed = [c for c in candidates if not re.search(r"_R\.webm$", os.path.basename(c), re.IGNORECASE)]
    _log("SAV5_found", count=len(non_reviewed), all=len(candidates))

    if not non_reviewed:
        # 🟡 All files are already reviewed — return friendly message
        return jsonify_safe({
            "stage": "skip",
            "message": "This file has already been reviewed and cannot be re-saved.",
            "glob": full_glob
        }, 200)

    candidates = non_reviewed

    def version_key(p):
        m = re.search(r"_v(\d+)", os.path.basename(p), re.IGNORECASE)
        v = int(m.group(1)) if m else -1
        return (v, os.path.getmtime(p))

    candidates.sort(key=version_key)
    src_path = candidates[-1]
    src_name = os.path.basename(src_path)

    # skip if already reviewed
    if re.search(r"_R\.webm$", src_name, re.IGNORECASE):
        _log("SAV5_skip", msg="Already reviewed file, skipping rename")
        return jsonify_safe({
            "stage": "skip",
            "message": "Already reviewed",
            "reviewed_path": src_path
        }, 200)

    # ---- build reviewed names ----------------------------------------------
    name_no_ext, _ = os.path.splitext(src_name)
    m = re.search(r"(_v\d+)(.*)$", name_no_ext, re.IGNORECASE)
    if m:
        version_part = m.group(1)
        base_prefix = name_no_ext[:m.start(1)]
        reviewed_name = f"{base_prefix}{version_part}_R.webm"
        reviewed_json = f"{base_prefix}{version_part}_R.json"
    else:
        reviewed_name = f"{name_no_ext}_R.webm"
        reviewed_json = f"{name_no_ext}_R.json"

    reviewed_path = os.path.join(target_dir, reviewed_name)
    json_path = os.path.join(target_dir, reviewed_json)

    # ---- SAV6: rename -------------------------------------------------------
    try:
        if os.path.exists(reviewed_path):
            try:
                os.remove(reviewed_path)
            except Exception as e:
                _log("SAV6_cleanup_warn", err=str(e))
        os.rename(src_path, reviewed_path)
        # ⭐ Copy to Favorites folder if checkbox was selected
        favorite = raw.get("favorite", False)
        if favorite:
            try:
                import shutil
                favorite_dir = r"\\GAAAP1PRD01W\Favorites"
                os.makedirs(favorite_dir, exist_ok=True)
                dest_path = os.path.join(favorite_dir, os.path.basename(reviewed_path))
                shutil.copy2(reviewed_path, dest_path)
                print(f"⭐ Copied favorite file to {dest_path}")
            except Exception as e:
                print(f"❌ Favorites copy error: {e}")

    except Exception as e:
        return jsonify_safe({
            "stage": "rename",
            "error": "Rename failed",
            "src": src_path,
            "dst": reviewed_path,
            "details": str(e)
        }, 500)

    annotations = raw.get("annotations", {}) or {}
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            stdjson.dump(annotations, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log("SAV7_json_err", err=str(e))
        return jsonify_safe({
            "stage": "json",
            "message": "Rename succeeded but JSON failed",
            "reviewed_path": reviewed_path,
            "json_path": json_path,
            "json_error": str(e)
        }, 207)

    return jsonify_safe({
        "stage": "done",
        "message": "Reviewed renamed + JSON saved",
        "reviewed_path": reviewed_path,
        "json_path": json_path
    }, 200)


    
@review_routes.route("/save_annotations", methods=["POST", "OPTIONS"])
def save_annotations():
    print(">>> /save_annotations HIT")
    data = request.get_json(force=True, silent=True)
    print(">>> BODY:", data)

    if request.method == "OPTIONS":
        response = make_response()
        response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "POST,OPTIONS")
        return response

    try:
        data = request.get_json()
        annotations = data.get("annotations", {})
        original_path = data.get("file_path")
        is_film = data.get("is_film", False)
        assignment_id = data.get("individual_assignment_id")
        grades = data.get("grades", [])
        force_grade_update = data.get("force_grade_update", False)

        if not original_path:
            return jsonify({"success": False, "error": "Missing file_path"}), 400

        dirname = os.path.dirname(original_path)
        filename = os.path.basename(original_path)
        base, ext = os.path.splitext(filename)

        # 🧹 Fix: if filename contains a wildcard (*), find the most recent reviewed file
        if "*" in base:
            try:
                # List all reviewed .webm files in this folder
                candidates = [
                    f for f in os.listdir(dirname)
                    if f.endswith(ext) and "_R" in f
                ]
                if candidates:
                    # Pick the most recently modified one
                    latest = max(candidates, key=lambda f: os.path.getmtime(os.path.join(dirname, f)))
                    base, _ = os.path.splitext(latest)
                    print(f"[INFO] Wildcard replaced with resolved base: {base}")
                else:
                    print("[WARN] No reviewed candidates found; keeping wildcard base.")
            except Exception as e:
                print(f"[WARN] Failed to resolve wildcard base: {e}")

        # 🟢 Reviewed path always gets the _R rename, regardless of annotations/notes
        if base.endswith("_R"):
            reviewed_path = os.path.join(dirname, f"{base}{ext}")
            reviewed_json_path = os.path.join(dirname, f"{base}.json")
        else:
            reviewed_path = os.path.join(dirname, f"{base}_R{ext}")
            reviewed_json_path = os.path.join(dirname, f"{base}_R.json")

            try:
                if os.path.exists(original_path):
                    os.rename(original_path, reviewed_path)
                    print(f"[OK] Renamed → {reviewed_path}")
            except Exception as e:
                print(f"[WARN] Rename failed: {e} — proceeding anyway")

        # 🖊️ Planning drawings are DB-backed (planning_files.file_path), not
        # filename-scanned like videos -- the rename above just orphaned that
        # row unless we repoint it at the new _R path too. Only do this if
        # the rename actually landed (it can silently fail on Windows with
        # WinError 32 if something still has the file open) -- otherwise
        # we'd point the DB row at a file that was never created, which is
        # worse than leaving it alone (videos self-heal via re-scan; this
        # table doesn't).
        try:
            normalized_original = original_path.replace("\\", "/")
            normalized_reviewed = reviewed_path.replace("\\", "/")
            rename_actually_happened = (
                normalized_original != normalized_reviewed
                and os.path.exists(reviewed_path)
                and not os.path.exists(original_path)
            )
            if rename_actually_happened:
                db_conn = get_db()
                db_conn.execute("""
                    UPDATE planning_files
                    SET file_path = ?, file_name = ?
                    WHERE file_path = ?
                """, (normalized_reviewed, os.path.basename(reviewed_path), normalized_original))
                db_conn.commit()
        except Exception as e:
            print(f"[WARN] planning_files path sync skipped: {e}")

        # ✅ Only write JSON when there's actual content — matches assignment behavior
        has_content = bool(annotations) or bool(data.get("notes"))
        if has_content:
            try:
                with open(reviewed_json_path, "w", encoding="utf-8") as f:
                    json.dump(annotations or {}, f, indent=2, ensure_ascii=False)
                print(f"[OK] JSON saved → {reviewed_json_path}")
            except Exception as e:
                print(f"[ERROR] JSON write failed: {e}")
        else:
            print("[OK] No annotations/notes — skipping JSON write")

        # ⭐ Copy to Favorites folder if checkbox was selected
        favorite = data.get("favorite", False)
        if favorite:
            try:
                favorite_dir = r"\\GAAAP1PRD01W\Favorites"
                os.makedirs(favorite_dir, exist_ok=True)

                # Copy only the reviewed video file
                src_video = reviewed_path
                dest_video = os.path.join(favorite_dir, os.path.basename(src_video))
                shutil.copy2(src_video, dest_video)

                print(f"⭐ Copied favorite file to {dest_video}")
            except Exception as e:
                print(f"❌ Favorites copy error in /save_annotations: {e}")



        statuses = []

        # 🩵 Assignment Grade Update Section (unchanged)
        if assignment_id and isinstance(grades, list) and (grades or force_grade_update):
            conn = get_db()
            cursor = conn.cursor()

            # 🟩 Case 1: explicit grades provided
            if grades:
                for g in grades:
                    step_id = g.get("step_id")
                    status = g.get("status")

                    # ✅ Save history before overwrite
                    save_grade_history(cursor, assignment_id, step_id, status)

                    cursor.execute("""
                        UPDATE individual_assignment_statuses
                        SET current_status = ?
                        WHERE individual_assignment_id = ? AND step_id = ?
                    """, (status, assignment_id, step_id))

                    node_row = cursor.execute(
                        "SELECT id FROM nodes WHERE name = ? AND step_id = ?",
                        (status, step_id)
                    ).fetchone()

                    if not node_row:
                        continue

                    parent_node_id = node_row["id"]
                    links = cursor.execute("""
                        SELECT child_node_id, to_flow_id
                        FROM links
                        WHERE parent_node_id = ?
                    """, (parent_node_id,)).fetchall()

                    for link in links:
                        child_node_id = link["child_node_id"]
                        to_flow_id = link["to_flow_id"] or step_id

                        child_name = cursor.execute(
                            "SELECT name FROM nodes WHERE id = ?",
                            (child_node_id,)
                        ).fetchone()

                        if not child_name:
                            continue

                        cursor.execute("""
                            UPDATE individual_assignment_statuses
                            SET current_status = ?
                            WHERE individual_assignment_id = ? AND step_id = ?
                        """, (child_name["name"], assignment_id, to_flow_id))

            # 🟩 Case 2: no explicit grade but force update requested
            elif force_grade_update:
                print(f"[FORCE] Grade update triggered for assignment_id={assignment_id}")
                cursor.execute("""
                    UPDATE individual_assignment_statuses
                    SET current_status = 'Graded'
                    WHERE individual_assignment_id = ?
                      AND current_status LIKE 'Grade%%'
                """, (assignment_id,))

            conn.commit()

            rows = cursor.execute("""
                SELECT s.id AS step_id, s.name AS step_name, ias.current_status AS status
                FROM individual_assignment_statuses ias
                JOIN steps s ON ias.step_id = s.id
                WHERE ias.individual_assignment_id = ?
                ORDER BY s.id ASC
            """, (assignment_id,)).fetchall()

            conn.close()

            statuses = [
                {"step_id": r["step_id"], "step_name": r["step_name"], "status": r["status"]}
                for r in rows
            ]

        # ✅ Response (same structure for films & assignments)
        return jsonify({
            "success": True,
            "message": "Saved successfully",
            "file": reviewed_path,
            "json": reviewed_json_path,
            "updated_statuses": statuses
        })

    except Exception as e:
        print("[ERROR] save_annotations:", e)
        return jsonify({"success": False, "error": str(e)}), 500


@review_routes.route("/update_scene_status", methods=["POST"])
def update_scene_status():
    data = request.get_json()
    print(">>> /update_scene_status HIT",
          "mode=", data.get("mode"),
          "scene_id=", data.get("scene_id"),
          "shot_id=", data.get("shot_id"),
          "step_id=", data.get("step_id"),
          "new_status=", data.get("new_status"))

    scene_id = data.get("scene_id")
    step_id = data.get("step_id")
    new_status = (data.get("new_status") or "").strip()
    mode = data.get("mode", "shot")
    shot_id = data.get("shot_id")

    if not scene_id or not step_id or not new_status:
        return jsonify({"error": "Missing required fields"}), 400

    conn = get_db()
    cur = conn.cursor()

    try:
        # 🔹 Get step name (used to detect FB steps)
        cur.execute("SELECT name FROM steps WHERE id = ?", (step_id,))
        row = cur.fetchone()
        step_name = row["name"] if row else "Unknown"
        step_name_upper = (step_name or "").upper()

        # 🔹 Get forward and reverse crossflow links
        # Links are per-status-node edges in the workflow markup diagram (e.g. a
        # "CUT" node on FB Animation wired straight to FB Lighting's "CUT" node,
        # to cascade cuts downstream). Without matching parent_node_id/child_node_id
        # to the actual new_status, a link meant only for one status (e.g. CUT)
        # gets applied on every status change of that step -- e.g. approving FB
        # Animation was incorrectly also approving FB Lighting via a CUT-only link.
        forward_links = cur.execute("""
            SELECT DISTINCT l.to_flow_id FROM links l
            JOIN nodes n ON n.id = l.parent_node_id
            WHERE l.step_id = ? AND l.to_flow_id IS NOT NULL
              AND LOWER(TRIM(n.name)) = LOWER(TRIM(?))
        """, (step_id, new_status)).fetchall()

        reverse_links = cur.execute("""
            SELECT DISTINCT l.step_id FROM links l
            JOIN nodes n ON n.id = l.child_node_id
            WHERE l.to_flow_id = ?
              AND LOWER(TRIM(n.name)) = LOWER(TRIM(?))
        """, (step_id, new_status)).fetchall()

        # Flatten lists
        forward_ids = [r["to_flow_id"] for r in forward_links if r["to_flow_id"]]
        reverse_ids = [r["step_id"] for r in reverse_links if r["step_id"]]

        # --- Determine direction ---
        if reverse_ids:
            linked_step_ids = reverse_ids
            direction = "reverse"
        else:
            linked_step_ids = forward_ids
            direction = "forward"

        # ✅ Override for FB-type steps (e.g., FB Layout, FB Animation)
        if "FB" in step_name_upper:
            direction = "forward"
            linked_step_ids = forward_ids or reverse_ids
            print(f"🔧 Forced FB direction to forward for step '{step_name}'")

        print(f"🔄 Crossflow direction: {direction} | Linked step_ids: {linked_step_ids}")

        # --- Helper to apply updates ---
        def update_status_for_step(sid):
            """
            Update or create status rows for the target step.
            sid: step_id to update
            """
            # --- SHOT MODE: update one row, insert if missing ---
            if mode == "shot" and shot_id:
                # try update
                cur.execute("""
                    UPDATE shot_step_assignments
                    SET status = ?
                    WHERE step_id = ? AND shot_id = ?
                """, (new_status, sid, shot_id))
                updated = cur.rowcount

                # insert if update didn't touch a row
                if updated == 0:
                    cur.execute("""
                        INSERT INTO shot_step_assignments (shot_id, step_id, status)
                        VALUES (?, ?, ?)
                    """, (shot_id, sid, new_status))
                    updated = 1  # reflect that we changed a row

                return updated

            # --- SCENE MODE: ensure rows exist for all shots in the scene, then update ---
            elif mode == "scene" and scene_id:
                # precreate any missing (shot_id, step_id) rows
                cur.execute("""
                    INSERT INTO shot_step_assignments (shot_id, step_id, status)
                    SELECT s.id, ?, ?
                    FROM shots s
                    WHERE s.scene_id = ?
                    AND NOT EXISTS (
                        SELECT 1 FROM shot_step_assignments a
                            WHERE a.shot_id = s.id AND a.step_id = ?
                    )
                """, (sid, new_status, scene_id, sid))

                # update them all to the new value
                cur.execute("""
                    UPDATE shot_step_assignments
                    SET status = ?
                    WHERE step_id = ?
                    AND shot_id IN (SELECT id FROM shots WHERE scene_id = ?)
                """, (new_status, sid, scene_id))
                return cur.rowcount

            return 0

        # --- Update main step ---
        affected = update_status_for_step(step_id)
        print(f"[OK] step_id={step_id} ({step_name}) → {new_status} | affected={affected}")

        # 🩸 Force persist if Cut somehow affected 0 rows
        if new_status.lower() == "cut" and affected == 0 and shot_id:
            cur.execute("""
                INSERT OR REPLACE INTO shot_step_assignments (shot_id, step_id, status)
                VALUES (?, ?, ?)
            """, (shot_id, step_id, new_status))
            conn.commit()
            print(f"🩸 Forced CUT write for shot_id={shot_id}, step_id={step_id}")


        # --- Update all linked steps (crossflow) ---
        crossflow_results = []
        for linked_id in linked_step_ids:
            aff = update_status_for_step(linked_id)
            crossflow_results.append({"step_id": linked_id, "affected": aff})
            print(f"[CROSSFLOW:{direction}] {step_id}:{new_status} → {linked_id}:{new_status} | affected={aff}")

        # 🩸 Deep cascade: mark CUT for this step and *all downstream* linked steps recursively
        def cascade_cut(step_ids, visited=None):
            if visited is None:
                visited = set()
            for sid in step_ids:
                if sid in visited:
                    continue
                visited.add(sid)
                cur.execute("""
                    INSERT INTO shot_step_assignments (shot_id, step_id, status)
                    VALUES (?, ?, ?)
                    ON CONFLICT(shot_id, step_id) DO UPDATE SET status = excluded.status
                """, (shot_id, sid, new_status))
                print(f"🩸 Forced cascade CUT → step_id={sid}, shot_id={shot_id}")

                # Get *next* downstream links
                next_links = cur.execute("""
                    SELECT DISTINCT to_flow_id FROM links
                    WHERE step_id = ? AND to_flow_id IS NOT NULL
                """, (sid,)).fetchall()
                next_ids = [r["to_flow_id"] for r in next_links if r["to_flow_id"]]
                if next_ids:
                    cascade_cut(next_ids, visited)

        if new_status.upper() == "CUT":
            print("🩸 Cascading CUT recursively through downstream steps")
            cascade_cut([step_id])
            conn.commit()


        conn.commit()

        # ✅ VERIFY the row we intended actually has the new status
        cur.execute("""
            SELECT status FROM shot_step_assignments
            WHERE shot_id = ? AND step_id = ?
        """, (shot_id, step_id))
        row = cur.fetchone()
        verified_status = row["status"] if row else None

        # (Optional) show DB file to detect connecting to the wrong db file
        try:
            cur.execute("PRAGMA database_list")
            dblist = [dict(seq=row) for row in cur.fetchall()]
        except Exception:
            dblist = []

        safe_dblist = []
        for r in dblist:
            if isinstance(r, sqlite3.Row):
                safe_dblist.append(dict(r))
            else:
                safe_dblist.append(r)

        response = {
            "message": f"Status updated (direction={direction})",
            "mode": mode,
            "new_status": new_status,
            "verified_status": verified_status,  # <= echo from DB
            "scene_id": scene_id,
            "shot_id": shot_id,
            "step_id": step_id,
            "affected": affected,
            "crossflow": crossflow_results,
            "dblist": safe_dblist,  # helps confirm the actual sqlite file path
        }

        print(f"🧩 RETURNING update_scene_status → {response}")
        if "dblist" in response:
            response["dblist"] = [
                dict(r) if isinstance(r, sqlite3.Row) else r
                for r in response["dblist"]
            ]

        # 🧠 DEBUG: Confirm DB actually contains Cut before return
        cur.execute("""
            SELECT shot_id, step_id, status
            FROM shot_step_assignments
            WHERE shot_id = ? AND step_id = ?
        """, (shot_id, step_id))
        final_check = cur.fetchone()
        print("🧠 FINAL DB CHECK:", dict(final_check) if final_check else "No row found")

        # ============================================================
        # ⭐ THUMBNAIL FINALIZE (Rename to _R.webm)
        # ============================================================
        try:
            # Only run for thumbnails — step name contains "THUMB"
            if "THUMB" in step_name_upper and new_status:

                cur.execute("""
                    SELECT sc.scene_number, f.name AS film_name
                    FROM shots sh
                    JOIN scenes sc ON sc.id = sh.scene_id
                    JOIN films f ON f.id = sc.film_id
                    WHERE sh.id = ?
                """, (shot_id,))
                r = cur.fetchone()

                if r:
                    scene_num = r["scene_number"].zfill(3)
                    film_name = r["film_name"]

                    thumb_dir = os.path.join(
                        r"\\GAAAP1PRD01W\Films",
                        film_name,
                        "Thumbnails",
                        f"{scene_num}_THUMB"
                    )

                    for fname in os.listdir(thumb_dir):
                        if fname.endswith(".webm") and "_R" not in fname:
                            src = os.path.join(thumb_dir, fname)
                            dst = src.replace(".webm", "_R.webm")

                            if os.path.exists(dst):
                                os.remove(dst)

                            os.rename(src, dst)
                            copy_to_reviewed_thumbnails(dst, film_name, scene_num)
                            break
            if "SB" in step_name_upper and new_status:

                cur.execute("""
                    SELECT s.scene_number, f.name AS film_name
                    FROM scenes s
                    JOIN films f ON f.id = s.film_id
                    WHERE s.id = ?
                """, (scene_id,))
                r = cur.fetchone()

                if r:
                    scene_num = r["scene_number"].zfill(3)
                    film_name = r["film_name"]

                    sb_dir = os.path.join(
                        r"\\GAAAP1PRD01W\Films",
                        film_name,
                        "Thumbnails",
                        f"{scene_num}_SB"
                    )

                    for fname in os.listdir(sb_dir):
                        if fname.endswith(".webm") and "_R" not in fname:
                            src = os.path.join(sb_dir, fname)
                            dst = src.replace(".webm", "_R.webm")

                            if os.path.exists(dst):
                                os.remove(dst)

                            os.rename(src, dst)
                            copy_to_reviewed_thumbnails(dst, film_name, scene_num)
                            break

        except Exception as thumb_err:
            print("❌ Thumbnail finalize error:", thumb_err)


        return jsonify_safe(response)


    except Exception as e:
        conn.rollback()
        print("❌ update_scene_status error:", e)
        return jsonify({"error": str(e)}), 500

    finally:
        cur.close()
        conn.close()

@review_routes.route("/update_grade", methods=["POST"])
def update_grade():
    """ Updates the grade for the exact row (matching step_id),
        and if update_crossflow=True, also updates its linked crossflow for the same process step. """
    data = request.get_json()
    individual_assignment_id = data.get("assignment_id")
    step_id = data.get("step_id")
    new_grade = data.get("new_grade")
    update_crossflow = data.get("update_crossflow", False)

    if not individual_assignment_id or not step_id or not new_grade:
        return jsonify({"error": "Missing assignment_id, step_id, or new_grade"}), 400

    print("📥 update_grade called:", request.json)

    conn = get_db()
    cursor = conn.cursor()

    save_grade_history(cursor, individual_assignment_id, step_id, new_grade)

    # ✅ Update only this row
    cursor.execute("""
        UPDATE individual_assignment_statuses 
        SET current_status = ? 
        WHERE individual_assignment_id = ? 
          AND step_id = ?
    """, (new_grade, individual_assignment_id, step_id))

    crossflow_updated = []
    if update_crossflow:
        # 🔍 Find crossflow links for this grade step
        cursor.execute("""
            SELECT to_flow_id, child_node_id
            FROM links
            WHERE step_id = ? AND to_flow_id IS NOT NULL
        """, (step_id,))
        link_rows = cursor.fetchall()

        for row in link_rows:
            to_flow_id = row["to_flow_id"]       # the process step affected (e.g. 224)
            child_node_id = row["child_node_id"] # the node we should set (e.g. 1207 Retake)

            # 🔎 Lookup the node's name (string to save)
            cursor.execute("SELECT name FROM nodes WHERE id = ?", (child_node_id,))
            node = cursor.fetchone()
            if not node:
                print(f"⚠️ No node found for child_node_id={child_node_id}")
                continue

            new_status_str = node["name"]

            # ✅ Update the linked process step (to_flow_id) with the node's string name
            cursor.execute("""
                UPDATE individual_assignment_statuses
                SET current_status = ?
                WHERE individual_assignment_id = ?
                AND step_id = ?
            """, (new_status_str, individual_assignment_id, to_flow_id))

            crossflow_updated.append({
                "to_flow_id": to_flow_id,
                "new_status": new_status_str
            })


    conn.commit()
    conn.close()

    return jsonify({
        "message": "Grade updated successfully!",
        "assignment_id": individual_assignment_id,
        "step_id": step_id,
        "new_assignment_status": new_grade,
        "crossflow_updated": crossflow_updated
    })


@review_routes.route("/download_review_file", methods=["GET"])
def download_review_file():
    file_path = request.args.get("file_path")

    if not file_path:
        return jsonify({"error": "Missing file_path"}), 400

    # Normalize slashes
    file_path = file_path.replace("/", "\\")

    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    return send_file(
        file_path,
        as_attachment=True,
        download_name=os.path.basename(file_path)
    )

# ----------------------------------------------------------------------------------------------------------------------
# DELETE FILES
# ----------------------------------------------------------------------------------------------------------------------
@review_routes.route("/delete_file", methods=["DELETE", "OPTIONS"])
def delete_file():
    from flask import make_response, request, jsonify
    from urllib.parse import unquote
    import os

    if request.method == "OPTIONS":
        response = make_response()
        response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "DELETE,OPTIONS")
        response.status_code = 200
        return response

    file_path = request.args.get("path")

    if not file_path:
        return jsonify({"error": "Missing file path"}), 400

    file_path = os.path.normpath(unquote(file_path))
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    try:
        os.remove(file_path)
        json_path = os.path.splitext(file_path)[0] + ".json"
        if os.path.exists(json_path):
            os.remove(json_path)

        # Planning drawings are DB-backed (planning_files.file_path) --
        # deleting only the disk file here (this route's original behavior,
        # built for filename-scanned videos with no DB row) would leave a
        # dangling row pointing at a file that no longer exists.
        try:
            normalized_path = file_path.replace("\\", "/")
            db_conn = get_db()
            db_conn.execute("DELETE FROM planning_files WHERE file_path = ?", (normalized_path,))
            db_conn.execute("DELETE FROM video_reference_files WHERE file_path = ?", (normalized_path,))
            db_conn.commit()
        except Exception as e:
            print(f"[WARN] planning_files/video_reference_files cleanup skipped: {e}")

        response = jsonify({"success": True, "message": "File deleted."})
        return response
    except Exception as e:
        response = jsonify({"error": str(e)})
        return response, 500

# ----------------------------------------------------------------------------------------------------------------------
# UTILS
# ----------------------------------------------------------------------------------------------------------------------
def get_current_semester_classes_full():
    term_order = {"SPRING": 1, "SUMMER": 2, "FALL": 3, "WINTER": 0}

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    sem_rows = cursor.execute("SELECT id, year, term FROM semesters").fetchall()
    if not sem_rows:
        conn.close()
        return [], None

    def sem_key(r):
        year = int(r["year"]) if r["year"] is not None else 0
        term = (r["term"] or "").strip().upper()
        return (year, term_order.get(term, 0))

    current_sem = max(sem_rows, key=sem_key)
    sem_id = current_sem["id"]

    class_rows = cursor.execute("""
        SELECT id, class_name
        FROM classes
        WHERE semester_id = ?
        ORDER BY class_name COLLATE NOCASE
    """, (sem_id,)).fetchall()

    conn.close()

    semester_label = f"{current_sem['year']}-{current_sem['term']}"
    return class_rows, semester_label

@review_routes.route("/current_semester_classes", methods=["GET"])
def current_semester_classes():
    classes, semester_label = get_current_semester_classes_full()

    print("🚨 CLASSES USED FOR ZIP:")
    for c in classes:
        print(c["class_name"])

    return jsonify({
        "semester": semester_label,
        "classes": [r["class_name"] for r in classes]
    })

def generate_canvas_csv_string(class_id):
    import csv, io, sqlite3

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    sql = """
    SELECT 
        c.class_name,
        u.name AS student_name,
        u.login_name AS login,
        a.name AS assignment_name,
        s.name AS step_name,
        MAX(ias.current_status) AS grade
        FROM individual_assignments ia
        JOIN users u ON ia.users_id = u.id
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN classes c ON a.class_id = c.id
        JOIN individual_assignment_statuses ias ON ia.id = ias.individual_assignment_id
        JOIN steps s ON ias.step_id = s.id
        WHERE s.name LIKE 'Grade%'
    """
    params = ()

    if class_id:
        sql += " AND c.id = ?"
        params = (class_id,)

    sql += """
        GROUP BY c.class_name, u.name, u.login_name, a.name, s.name
        ORDER BY u.name, a.name
    """

    rows = cursor.execute(sql, params).fetchall()
    conn.close()

    if not rows:
        return None, None

    assignments = sorted(set(f"{r['assignment_name']} - {r['step_name']}" for r in rows))

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")

    writer.writerow(["Student", "", "", "", "", *assignments])
    writer.writerow(["Points Possible", "", "", "", "", *["5"] * len(assignments)])

    by_student = {}
    class_name = rows[0]["class_name"]

    for r in rows:
        grade_val = r["grade"].split("-")[0].strip() if r["grade"] else "0"

        if r["student_name"] not in by_student:
            by_student[r["student_name"]] = {"login": r["login"], "grades": {}}

        col_name = f"{r['assignment_name']} - {r['step_name']}"
        by_student[r["student_name"]]["grades"][col_name] = grade_val

    for student, sdata in by_student.items():
        row_out = [student, "", "", sdata["login"], class_name]

        for a in assignments:
            row_out.append(sdata["grades"].get(a, "0"))

        writer.writerow(row_out)

    output.seek(0)
    return output.getvalue(), class_name

POSE_PARENT_STEP_ID = 342


def _canvas_norm(s):
    """Normalize a column / assignment label for loose matching.

    Lowercases, collapses whitespace, and strips spaces around dashes so that
    'Jump - Grade-Planning' and 'Obstacle Course- Grade-Planning' compare equal
    to the labels we build internally.
    """
    if not s:
        return ""
    s = re.sub(r"\s+", " ", str(s)).strip().lower()
    s = re.sub(r"\s*-\s*", "-", s)
    return s


def _canvas_extract_numeric(status_string):
    """Pull the numeric value from a grade string e.g. '3 - B' -> 3.0"""
    if not status_string:
        return 0.0
    try:
        return float(str(status_string).split(" - ")[0].strip())
    except (ValueError, IndexError):
        return 0.0


def _fmt_num(val):
    return str(int(val)) if float(val) == int(val) else str(val)


def _build_canvas_grade_data(class_filter):
    """Return (class_name, students, alias_map).

    students: list of {name, login, aliases: {alias_norm: numeric}}
    alias_map: {alias_norm: human_label} across the whole class (for diagnostics)

    Pose assignments (parent_step_id == 342) collapse all of their grade steps
    into a single value per assignment (Grade Pose 1 + Grade Pose 2, ...).
    Non-pose assignments produce one value per 'Grade%' step.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Resolve the current semester the same way the class picker does, so an
    # old section that shares a class name isn't pulled in.
    term_order = {"WINTER": 0, "SPRING": 1, "SUMMER": 2, "FALL": 3}
    sem_rows = cursor.execute("SELECT id, year, term FROM semesters").fetchall()
    current_sem_id = None
    if sem_rows:
        current_sem_id = max(
            sem_rows,
            key=lambda r: (
                int(r["year"]) if r["year"] is not None else 0,
                term_order.get((r["term"] or "").strip().upper(), 0),
            ),
        )["id"]

    sql = """
    SELECT
        c.class_name,
        u.name AS student_name,
        u.login_name AS login,
        a.id AS assignment_id,
        a.name AS assignment_name,
        a.parent_step_id,
        s.name AS step_name,
        ias.current_status AS grade
    FROM individual_assignments ia
    JOIN users u ON ia.users_id = u.id
    JOIN assignments a ON ia.assignment_id = a.id
    JOIN classes c ON a.class_id = c.id
    -- Only students enrolled in THIS class for the current semester
    JOIN class_enrollments ce
        ON ce.user_id = u.id
       AND ce.class_id = c.id
       AND (ce.semester_id = c.semester_id OR ce.semester_id IS NULL)
    JOIN individual_assignment_statuses ias ON ia.id = ias.individual_assignment_id
    JOIN steps s ON ias.step_id = s.id
    WHERE s.name LIKE 'Grade%'
      AND COALESCE(c.archived, 0) = 0
    """
    params = []
    if current_sem_id is not None:
        sql += " AND c.semester_id = ?"
        params.append(current_sem_id)
    if class_filter:
        sql += " AND c.class_name = ?"
        params.append(class_filter)
    sql += " ORDER BY u.name, a.name, s.name"

    rows = cursor.execute(sql, tuple(params)).fetchall()
    if not rows:
        return None, [], {}

    class_name = rows[0]["class_name"]

    # How many grade steps does each non-pose assignment have? A single-step
    # assignment can also be matched by its bare name ("Walk Entire Character").
    step_counts = {}
    for r in rows:
        if r["parent_step_id"] != POSE_PARENT_STEP_ID:
            step_counts.setdefault(r["assignment_name"], set()).add(r["step_name"])

    by_student = {}
    alias_map = {}

    counted = set()  # (student, assignment, step) already applied — guards pose double-count
    for r in rows:
        key = r["login"] or r["student_name"]
        st = by_student.setdefault(
            key, {"name": r["student_name"], "login": r["login"], "aliases": {}}
        )

        dedupe_key = (key, r["assignment_name"], r["step_name"])
        if dedupe_key in counted:
            continue
        counted.add(dedupe_key)

        numeric = _canvas_extract_numeric(r["grade"])

        if r["parent_step_id"] == POSE_PARENT_STEP_ID:
            labels = [r["assignment_name"]]  # e.g. "Pose #1" -- steps are summed
            combine = True
        else:
            labels = [f"{r['assignment_name']} - {r['step_name']}"]
            if len(step_counts.get(r["assignment_name"], ())) == 1:
                labels.append(r["assignment_name"])
            combine = False

        for label in labels:
            alias = _canvas_norm(label)
            alias_map.setdefault(alias, label)
            if combine:
                st["aliases"][alias] = st["aliases"].get(alias, 0) + numeric
            else:
                st["aliases"][alias] = numeric

    return class_name, list(by_student.values()), alias_map


def _match_canvas_column(col_norm, alias_map):
    """Match a Canvas column (normalized, id suffix stripped) to an internal alias."""
    if col_norm in alias_map:
        return col_norm
    # Prefix match: "pose #1 line of action" -> "pose #1"
    for alias in alias_map:
        if col_norm == alias or col_norm.startswith(alias + " "):
            return alias
    return None


@review_routes.route("/export_canvas_csv", methods=["GET", "POST"])
def export_canvas_csv():
    """Export grades as a Canvas-importable CSV.

    POST (preferred): multipart form with a `template` file -- the gradebook CSV
    exported from Canvas. The response reuses that file's exact header and
    Points Possible rows (so every column, including the `(id)` suffix Canvas
    matches on, lines up) and only fills in the columns we can map to internal
    grades. Unmatched assignment columns are reported in the
    `X-Unmatched-Columns` response header.

    GET (fallback): best-effort export with generated column names.
    """
    import csv, io

    class_filter = request.args.get("class") or request.form.get("class")
    template_file = request.files.get("template") if request.method == "POST" else None

    class_name, students, alias_map = _build_canvas_grade_data(class_filter)
    if class_name is None:
        return jsonify({"error": "No grade rows found", "class_filter": class_filter}), 404

    ID_COL_RE = re.compile(r"^(.*?)\s*\((\d+)\)\s*$")

    def _send(text, unmatched=None, matched=None):
        resp = make_response(("﻿" + text).encode("utf-8"))
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", class_name).strip("_") or "grades"
        resp.headers["Content-Disposition"] = f'attachment; filename="{safe}.csv"'
        resp.headers["Access-Control-Expose-Headers"] = "X-Unmatched-Columns, X-Matched-Columns"
        if unmatched is not None:
            resp.headers["X-Unmatched-Columns"] = stdjson.dumps(unmatched)
        if matched is not None:
            resp.headers["X-Matched-Columns"] = stdjson.dumps(matched)
        return resp

    # ---- Template-aligned mode ---------------------------------------------
    if template_file is not None:
        raw = template_file.read().decode("utf-8-sig", errors="replace")
        reader = list(csv.reader(io.StringIO(raw)))
        if len(reader) < 2:
            return jsonify({"error": "Template CSV has no header / Points Possible rows"}), 400

        header = reader[0]
        points_row = reader[1]

        try:
            login_idx = next(
                i for i, h in enumerate(header)
                if h.strip().lower() in ("sis login id", "sis user id", "login id")
            )
        except StopIteration:
            login_idx = 3

        col_targets = {}   # header index -> internal alias
        unmatched = []
        matched = []
        for i, h in enumerate(header):
            m = ID_COL_RE.match(h.strip())
            if not m:
                continue  # Student / ID / Section / read-only aggregate columns
            alias = _match_canvas_column(_canvas_norm(m.group(1)), alias_map)
            if alias:
                col_targets[i] = alias
                matched.append(h.strip())
            else:
                unmatched.append(h.strip())

        def _name_key(s):
            return " ".join(sorted(re.findall(r"[a-z]+", (s or "").lower())))

        by_login = {}
        by_name = {}
        for s in students:
            if s["login"]:
                by_login[s["login"].strip().lower()] = s
            if s["name"]:
                by_name.setdefault(_name_key(s["name"]), s)

        out = io.StringIO(newline="")
        writer = csv.writer(out, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerow(points_row)

        seen = set()
        for row in reader[2:]:
            if not any(cell.strip() for cell in row):
                continue
            row = list(row) + [""] * (len(header) - len(row))
            login = row[login_idx].strip().lower() if login_idx < len(row) else ""
            student = by_login.get(login) or by_name.get(_name_key(row[0]))
            if student:
                seen.add(id(student))
                for idx, alias in col_targets.items():
                    if alias in student["aliases"]:
                        row[idx] = _fmt_num(student["aliases"][alias])
            writer.writerow(row[:len(header)])

        # Students we have grades for who were not already in the template.
        extras = 0
        for student in students:
            if id(student) in seen:
                continue
            extras += 1
            row = [""] * len(header)
            row[0] = student["name"] or ""
            if login_idx < len(header):
                row[login_idx] = student["login"] or ""
            for idx, alias in col_targets.items():
                if alias in student["aliases"]:
                    row[idx] = _fmt_num(student["aliases"][alias])
            writer.writerow(row)

        if extras:
            matched.append(f"(+{extras} student rows appended, not in template)")

        return _send(out.getvalue(), unmatched=unmatched, matched=matched)

    # ---- Fallback mode (no template) --------------------------------------
    col_labels = []
    seen = set()
    for label in alias_map.values():
        if label not in seen:
            col_labels.append(label)
            seen.add(label)

    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["Student", "ID", "SIS User ID", "SIS Login ID", "Section", *col_labels])
    writer.writerow(["    Points Possible", "", "", "", "", *["" for _ in col_labels]])
    for s in students:
        row_out = [s["name"], "", "", s["login"], class_name]
        for label in col_labels:
            val = s["aliases"].get(_canvas_norm(label))
            row_out.append(_fmt_num(val) if val is not None else "")
        writer.writerow(row_out)

    return _send(out.getvalue())


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMP_DIR = os.path.join(BASE_DIR, "temp_exports")

@review_routes.route("/export_all_grades_zip")
def export_all_grades_zip():
    import os, zipfile, sqlite3
    from datetime import datetime
    from flask import send_file

    os.makedirs(TEMP_DIR, exist_ok=True)

    zip_filename = f"all_classes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = os.path.join(TEMP_DIR, zip_filename)

    print("ZIP PATH:", zip_path)

    # 🔥 THIS IS THE FIX
    classes, _ = get_current_semester_classes_full()

    print("🚨 CLASSES USED IN ZIP:")
    for c in classes:
        print(c["class_name"])

    with zipfile.ZipFile(zip_path, "w") as zipf:
        for row in classes:
            class_id = row["id"]
            class_name = row["class_name"]

            csv_string, _ = generate_canvas_csv_string(class_id)

            if not csv_string:
                continue

            safe_name = "".join(c for c in class_name if c.isalnum() or c in " _-").replace(" ", "_")
            zipf.writestr(f"{safe_name}.csv", "\ufeff" + csv_string)

    return send_file(zip_path, as_attachment=True)

# ----------------------------------------------------------------------------------------------------------------------
# USER PREFERENCES
# ----------------------------------------------------------------------------------------------------------------------

@review_routes.route("/preferences/<int:user_id>", methods=["GET"])
def get_user_preferences(user_id):
    """Return user preferences, create defaults if missing."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,))
    prefs = cursor.fetchone()

    if not prefs:
        cursor.execute("INSERT INTO user_preferences (user_id) VALUES (?)", (user_id,))
        conn.commit()
        cursor.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,))
        prefs = cursor.fetchone()

    conn.close()
    return jsonify(dict(prefs))


@review_routes.route("/preferences/<int:user_id>", methods=["POST"])
def update_user_preferences(user_id):
    """Update brush, color, and onion skin preferences."""
    data = request.get_json()
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE user_preferences
        SET brush_size = ?,
            brush_color = ?,
            onion_skin_opacity = ?,
            onion_skin_frames = ?
        WHERE user_id = ?
    """, (
        data.get("brush_size", 5),
        data.get("brush_color", "#FF0000"),
        data.get("onion_skin_opacity", 0.5),
        data.get("onion_skin_frames", 2),
        user_id
    ))

    conn.commit()
    conn.close()
    return jsonify({"message": "Preferences updated"})



# ----------------------------------------------------------------------------------------------------------------------
# Create movie
# ----------------------------------------------------------------------------------------------------------------------

@review_routes.route("/concat_scene/<scene_id>/<step_code>", methods=["POST"])
def concat_scene(scene_id, step_code):
    print("🧩 concat_scene() HIT with:", scene_id, step_code)
    """
    Combine all shots in this scene + step (e.g., LAY) into one video clip.
    Caches result in \\GAAAP1PRD01W\\Films\\<film>\\<scene>\\review_clips\\
    and rebuilds only if shot files are newer.
    """
    import os, subprocess, tempfile, time
    from flask import jsonify, send_file
    from datetime import datetime

    conn = get_db()
    cur = conn.cursor()

    # Get film name and scene number from DB
    cur.execute("""
        SELECT f.name, s.scene_number
        FROM scenes s
        JOIN films f ON s.film_id = f.id
        WHERE s.id = ?
    """, (scene_id,))
    result = cur.fetchone()
    
    if not result:
        print("⚠️ 404: Scene not found")
        return jsonify({"error": "Scene not found"}), 404

    print("🎯 DB Query → Scene ID:", scene_id)
    print("🎯 Query result →", result)


    film_name, scene_num = result
    film_folder = f"\\\\GAAAP1PRD01W\\Films\\{film_name}\\{scene_num}"
    review_folder = os.path.join(film_folder, "review_clips")

    os.makedirs(review_folder, exist_ok=True)

    output_file = os.path.join(review_folder, f"{film_name}_{scene_num}_{step_code}_Review.webm")

    # Gather all valid LAY shot paths
    cur.execute("""
        SELECT s.shot_number
        FROM shots s
        JOIN scenes sc ON s.scene_id = sc.id
        WHERE sc.id = ?
        ORDER BY s.shot_number ASC
    """, (scene_id,))

    shots = cur.fetchall()

    if not shots:
        print("⚠️ 404: No shots found (scene_number)", scene_id)
        return jsonify({"error": "No shots found"}), 404

    file_list = []
    for (shot_num,) in shots:
        pattern = f"{film_name}_{scene_num}_{str(shot_num).zfill(3)}_{step_code}_*.webm"
        folder = os.path.join(film_folder, str(shot_num).zfill(3))

        if not os.path.exists(folder):
            continue

        # Find the newest version matching the pattern
        matching = [f for f in os.listdir(folder) if f.endswith(".webm") and pattern.split("_*.")[0] in f]
        if not matching:
            continue

        latest = max(matching, key=lambda f: os.path.getmtime(os.path.join(folder, f)))
        full_path = os.path.join(folder, latest)
        file_list.append(full_path)

    if not file_list:
        print("⚠️ 404: No valid .webm files found")
        return jsonify({"error": "No valid .webm files found"}), 404

    # Check cache validity
    if os.path.exists(output_file):
        output_time = os.path.getmtime(output_file)
        newest_shot_time = max(os.path.getmtime(f) for f in file_list)
        if newest_shot_time < output_time:
            print(f"✅ Using cached review clip: {output_file}")
            return send_file(output_file, mimetype="video/webm")

    # Build FFmpeg list
    list_file = os.path.join(tempfile.gettempdir(), f"concat_{film_name}_{scene_num}_{step_code}.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in file_list:
            f.write(f"file '{p}'\n")

    print(f"🎬 Building new combined clip for {film_name} Scene {scene_num} ({len(file_list)} shots)...")

    cmd = [
        r"C:\ffmpeg\bin\ffmpeg.exe", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output_file
    ]


    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        print("❌ FFmpeg error:", e.stderr.decode("utf-8"))
        return jsonify({"error": "FFmpeg failed"}), 500

    if not os.path.exists(output_file):
        print("⚠️ 500: Concat failed")
        return jsonify({"error": "Concat failed"}), 500

    print(f"✅ Created new combined review clip: {output_file}")
    return send_file(output_file, mimetype="video/webm")


@review_routes.route("/scene_reviews")
def scene_reviews():
    """
    Display a simple list of review clips found in Films/*/*/review_clips
    """
    import os
    from flask import render_template

    base_path = r"\\GAAAP1PRD01W\Films"
    review_clips = []

    # Walk through films > scenes > review_clips
    for film in os.listdir(base_path):
        film_path = os.path.join(base_path, film)
        if not os.path.isdir(film_path):
            continue

        for scene in os.listdir(film_path):
            scene_path = os.path.join(film_path, scene, "review_clips")
            if os.path.exists(scene_path):
                for f in os.listdir(scene_path):
                    if f.endswith(".webm"):
                        review_clips.append({
                            "film": film,
                            "scene": scene,
                            "file": f,
                            "path": f"/review/get_video?path={scene_path}\\{f}"
                        })

    return render_template("scene_reviews.html", review_clips=review_clips)


@review_routes.route("/delete_review_clip", methods=["POST"])
def delete_review_clip():
    """
    Delete a specific review clip file.
    """
    import os
    from flask import request, jsonify

    data = request.get_json()
    clip_path = data.get("path")

    if not clip_path or not os.path.exists(clip_path):
        return jsonify({"error": "File not found"}), 404

    try:
        os.remove(clip_path)
        print(f"🗑️ Deleted review clip: {clip_path}")
        return jsonify({"success": True})
    except Exception as e:
        print("❌ Delete failed:", e)
        return jsonify({"error": str(e)}), 500

# ----------------------------------------------------------------------------------------------------------------------
# USER PERMISSIONS
# ----------------------------------------------------------------------------------------------------------------------

@review_routes.route("/get_permissions", methods=["GET"])
def get_permissions():
    """Return the current user's permission levels from session."""
    perms = session.get("permissions", {})
    return jsonify(perms)
