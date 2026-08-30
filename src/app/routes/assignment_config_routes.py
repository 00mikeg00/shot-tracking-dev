from flask import Blueprint, request, jsonify, current_app
import os
import json
from app.database.db import get_db
from app.utils.auth_utils import login_required
from datetime import datetime, date
import logging
logging.basicConfig(level=logging.DEBUG)

config_bp = Blueprint('config_bp', __name__)

RIGS_FOLDER = os.getenv("RIGS_ROOT", "C:/Cincy/Rigs")
RIG_EXTS = (".mb", ".ma", ".fbx")

# Same server as every class's Assignments/Scenes folder (see
# app/services/assignment_service.py's CLASS_FOLDER_ROOT), but a sibling
# folder a coordinator has to deliberately navigate to -- not the Scenes
# folder itself, which students already browse for their own versioned
# files and could stumble onto a raw starter scene in.
CLASS_FOLDER_ROOT = r"\\GAAAP1PRD01W\Classes"
STARTER_SCENE_EXTS = (".ma", ".mb")


def _list_starter_scenes(semester_name, class_name):
    """
    Every .ma/.mb file directly under this class's Assignments/StarterScenes
    folder -- a coordinator drops files there by hand (no upload flow),
    this just lists what's already present so the Config Editor can offer
    them as a dropdown. Missing folder is normal (most classes won't use
    this), not an error.
    """
    folder = os.path.join(CLASS_FOLDER_ROOT, semester_name, class_name, "Assignments", "StarterScenes")
    if not os.path.isdir(folder):
        return []
    try:
        return sorted(
            os.path.join(folder, f).replace("\\", "/")
            for f in os.listdir(folder)
            if f.lower().endswith(STARTER_SCENE_EXTS)
        )
    except OSError:
        return []

@config_bp.route('/semesters', methods=['GET'])
@login_required
def get_semesters():
    conn = get_db()
    cursor = conn.cursor()

    # make sure semesters table has start_date and end_date columns
    semesters = cursor.execute("""
        SELECT id, year, term, start_date, end_date
        FROM semesters
        ORDER BY year DESC, term ASC
    """).fetchall()


    today = date.today()

    result = []
    for s in semesters:
        is_current = False
        start = s["start_date"]
        end = s["end_date"]

        try:
            # Convert from string to date (if not None)
            if isinstance(start, str):
                start = datetime.strptime(start, "%Y-%m-%d").date()
            if isinstance(end, str):
                end = datetime.strptime(end, "%Y-%m-%d").date()
        except Exception:
            # If parsing fails, just skip marking as current
            start = end = None

        if start and end:
            is_current = start <= today <= end

        result.append({
            "id": s["id"],
            "year": s["year"],
            "term": s["term"],
            "current": is_current
        })

    return jsonify(result)

@config_bp.route('/assignment-config/by-semester/<int:semester_id>', methods=['GET'])
@login_required
def get_assignment_config_by_semester(semester_id):
    conn = get_db()
    cursor = conn.cursor()

    semester_row = cursor.execute("SELECT year || '-' || term AS name FROM semesters WHERE id = ?", (semester_id,)).fetchone()
    if not semester_row:
        return jsonify({"error": "Semester not found"}), 404

    semester = semester_row['name']

    class_rows = cursor.execute("""
        SELECT c.id as class_id, c.class_name
        FROM classes c
        WHERE c.semester_id = ?
    """, (semester_id,)).fetchall()

    rigs_folder = "C:/Cincy/Rigs"
    rig_files = []
    for root, _, files in os.walk(rigs_folder):
        for file in files:
            if file.lower().endswith(('.mb', '.ma')):
                rig_files.append(os.path.join(root, file).replace("\\", "/"))

    result = {
        "semester": semester,
        "classes": {},
        "rigs": rig_files
    }

    for row in class_rows:
        class_id = row['class_id']
        class_name = row['class_name']
        result['classes'][class_name] = {}

        assignments = cursor.execute("SELECT name FROM assignments WHERE class_id = ? ORDER BY name", (class_id,)).fetchall()
        presets = cursor.execute("""
            SELECT assignment_name, rigs, camera, filename, frame_start, frame_end
            FROM assignment_config_presets
            WHERE class_id = ?
        """, (class_id,)).fetchall()
        preset_map = {
            p['assignment_name']: {
                'rigs': json.loads(p['rigs']) if p['rigs'] else [],
                'camera': bool(p['camera']),
                'filename': p['filename'] or "",
                'frame_start': p['frame_start'],
                'frame_end': p['frame_end']
            } for p in presets
        }

        for assignment in assignments:
            a_name = assignment['name']
            preset = preset_map.get(a_name, {"rigs": [], "camera": False, "filename": "", "frame_start": None, "frame_end": None})
            result['classes'][class_name][a_name] = preset

    return jsonify(result)

@config_bp.route('/assignment-config/save-semester/<semester_id>', methods=['POST'])
@login_required
def save_assignment_config_semester(semester_id):
    """
    Saves the assignment configuration for a semester.
    Accepts either numeric IDs or text-based names like '2025-Fall' or 'Semester-2025'.
    """
    import json, os, tempfile
    from flask import request, jsonify
    from app.database.db import get_db

    data = request.get_json() or {}
    classes = data.get("classes", {})

    conn = get_db()
    cursor = conn.cursor()

    # ✅ Handle "-1" or unknown semester IDs gracefully
    original_semester_id = semester_id
    if str(semester_id).strip() == "-1":
        # ✅ Fallback: find the most recent semester by year and term order
        print("⚙️ No 'current' column — selecting most recent semester by year/term.")
        cursor.execute("""
            SELECT id FROM semesters
            ORDER BY year DESC,
                    CASE term
                        WHEN 'Spring' THEN 1
                        WHEN 'Summer' THEN 2
                        WHEN 'Fall' THEN 3
                        ELSE 4
                    END DESC
            LIMIT 1
        """)
        row = cursor.fetchone()

        if row:
            semester_id = row["id"]
            print(f"✅ Using latest semester ID: {semester_id}")
        else:
            print("⚠️ No semesters found in database.")
            semester_id = None


    elif not str(semester_id).isdigit():
        print(f"🔍 Converting semester identifier '{semester_id}' to ID...")
        cursor.execute("""
            SELECT id FROM semesters
            WHERE (year || '-' || term = ?)
               OR ('Semester-' || year || '-' || term = ?)
               OR ('Semester-' || year = ?)
        """, (semester_id, semester_id, semester_id))
        row = cursor.fetchone()
        if row:
            semester_id = row["id"]
            print(f"✅ Found matching semester ID: {semester_id}")
        else:
            print(f"⚠️ No matching semester found for '{original_semester_id}', defaulting to current semester.")
            cursor.execute("SELECT id FROM semesters WHERE current = 1")
            row = cursor.fetchone()
            semester_id = row["id"] if row else None

    if semester_id is None:
        return jsonify({"success": False, "error": f"Invalid semester identifier: {original_semester_id}"}), 400


    # ✅ Fetch semester name for labeling
    semester_row = cursor.execute(
        "SELECT year || '-' || term AS name FROM semesters WHERE id = ?",
        (semester_id,)
    ).fetchone()

    semester_name = semester_row["name"] if semester_row else f"Semester-{semester_id}"
    print(f"💾 Saving config (semester: {semester_name})")
    print(f"📦 Classes received: {list(classes.keys())}")


    json_obj = {
        "semester": {
            "name": semester_name
        }
    }

    for class_name, assignments in classes.items():
        json_obj["semester"][class_name] = {}
        print(f"🧩 Saving class '{class_name}' ({len(assignments)} assignments)")

        # ✅ Try to find the class in the DB (optional)
        cursor.execute("SELECT id FROM classes WHERE class_name = ?", (class_name,))
        row = cursor.fetchone()

        if not row:
            print(f"ℹ️ Class '{class_name}' not in database — skipping DB write.")
            class_id = None
        else:
            class_id = row["id"]
            cursor.execute("DELETE FROM assignment_config_presets WHERE class_id = ?", (class_id,))

        # ✅ Always include the data in the JSON file
        for assignment_name, cfg in assignments.items():
            raw_rigs = cfg.get("rigs", [])
            camera = bool(cfg.get("camera", False))
            # Blank filename breaks the dashboard version scan for the section;
            # fall back to the assignment name (the key GAA Save uses too).
            filename = (cfg.get("filename") or "").strip() or assignment_name
            frame_start = cfg.get("frame_start")
            frame_end = cfg.get("frame_end")
            frame_start = int(frame_start) if frame_start not in (None, "") else None
            frame_end = int(frame_end) if frame_end not in (None, "") else None

            # ✅ Normalize rigs — always list of { "path": "..." }
            rigs = []
            for r in raw_rigs:
                if isinstance(r, str):
                    rigs.append({"path": r})
                elif isinstance(r, dict):
                    # flatten nested {"path": {"path": {"path": "..."}}}
                    rig_path = r
                    while isinstance(rig_path, dict) and "path" in rig_path:
                        rig_path = rig_path["path"]
                    if isinstance(rig_path, str):
                        rigs.append({"path": rig_path})

            json_obj["semester"][class_name][assignment_name] = {
                "rigs": rigs,
                "camera": camera,
                "filename": filename,
                "frame_start": frame_start,
                "frame_end": frame_end
            }


            if class_id:
                cursor.execute("""
                    INSERT INTO assignment_config_presets (class_id, assignment_name, rigs, camera, filename, frame_start, frame_end)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (class_id, assignment_name, json.dumps(rigs), camera, filename, frame_start, frame_end))

    conn.commit()

    # ✅ Always write to the JSON file
    os.makedirs(r"C:\Cincy\Configs", exist_ok=True)
    output_path = os.path.join(r"C:\Cincy\Configs", "assignments_config.json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(json_obj, f, indent=2)

    print(f"✅ Config saved successfully to {output_path}")

    # ✅ Mirror to artscifs1 so lab machine installs can pull from
    # %SRC%\Configs like every other asset, instead of the c$ admin
    # share on GAAAP1PRD01W (SYSTEM-as-another-machine has no rights
    # there -- confirmed via install_log ERROR 5, 2026-08-10).
    share_warning = None
    share_dir = r"\\artscifs1.ad.uc.edu\Departments\GAA\UC_GAA\Configs"
    share_path = os.path.join(share_dir, "assignments_config.json")
    try:
        os.makedirs(share_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=share_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(json_obj, f, indent=2)
            os.replace(tmp_path, share_path)
            print(f"✅ Config mirrored to {share_path}")
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
    except Exception as share_err:
        share_warning = f"Saved locally, but sync to share failed: {share_err}"
        print(f"⚠️ {share_warning}")

    resp = {"success": True, "path": output_path}
    if share_warning:
        resp["warning"] = share_warning
    return jsonify(resp)


@config_bp.route('/assignment-config/by-class/<int:class_id>', methods=['GET'])
@login_required
def get_assignment_config_by_class(class_id):
    """
    Same per-class assignment/preset resolution as
    get_assignment_config_by_semester()'s inner loop, scoped to one class --
    backs the per-class Config Editor (classes.html's "Config" button per
    row) instead of the old whole-semester editor.
    """
    conn = get_db()
    cursor = conn.cursor()

    class_row = cursor.execute("""
        SELECT c.id, c.class_name, c.semester_id, s.year || '-' || s.term AS semester_name
        FROM classes c
        JOIN semesters s ON s.id = c.semester_id
        WHERE c.id = ?
    """, (class_id,)).fetchone()
    if not class_row:
        return jsonify({"error": "Class not found"}), 404

    assignments = cursor.execute(
        "SELECT name FROM assignments WHERE class_id = ? ORDER BY name", (class_id,)
    ).fetchall()
    presets = cursor.execute("""
        SELECT assignment_name, rigs, camera, filename, frame_start, frame_end, starter_scene
        FROM assignment_config_presets
        WHERE class_id = ?
    """, (class_id,)).fetchall()
    preset_map = {
        p['assignment_name']: {
            'rigs': json.loads(p['rigs']) if p['rigs'] else [],
            'camera': bool(p['camera']),
            'filename': p['filename'] or "",
            'frame_start': p['frame_start'],
            'frame_end': p['frame_end'],
            'starter_scene': p['starter_scene'] or ""
        } for p in presets
    }

    result_assignments = {}
    for a in assignments:
        name = a['name']
        result_assignments[name] = preset_map.get(
            name, {"rigs": [], "camera": False, "filename": "", "frame_start": None, "frame_end": None, "starter_scene": ""}
        )

    rigs_folder = "C:/Cincy/Rigs"
    rig_files = []
    for root, _, files in os.walk(rigs_folder):
        for file in files:
            if file.lower().endswith(('.mb', '.ma')):
                rig_files.append(os.path.join(root, file).replace("\\", "/"))

    return jsonify({
        "class_id": class_row["id"],
        "class_name": class_row["class_name"],
        "semester_id": class_row["semester_id"],
        "semester_name": class_row["semester_name"],
        "assignments": result_assignments,
        "rigs": rig_files,
        "starter_scenes": _list_starter_scenes(class_row["semester_name"], class_row["class_name"])
    })


@config_bp.route('/assignment-config/save-class/<int:class_id>', methods=['POST'])
@login_required
def save_assignment_config_class(class_id):
    """
    Saves ONE class's assignment config. DB presets are scoped to this
    class_id (delete + reinsert, same shape as
    save_assignment_config_semester()), but the JSON file write MERGES
    just this class's entry into whatever's already in
    assignments_config.json instead of overwriting the whole file --
    the old whole-semester editor opened with an empty in-memory class
    list that had to be manually repopulated per class before Save, so
    saving after only editing one class silently dropped every other
    class from the file. Scoping the editor (and this save) to one class
    at a time removes that trap entirely.
    """
    import tempfile

    data = request.get_json() or {}
    assignments = data.get("assignments", {})

    conn = get_db()
    cursor = conn.cursor()

    class_row = cursor.execute("""
        SELECT c.id, c.class_name, c.semester_id, s.year || '-' || s.term AS semester_name
        FROM classes c
        JOIN semesters s ON s.id = c.semester_id
        WHERE c.id = ?
    """, (class_id,)).fetchone()
    if not class_row:
        return jsonify({"success": False, "error": "Class not found"}), 404

    class_name = class_row["class_name"]
    semester_name = class_row["semester_name"]

    cursor.execute("DELETE FROM assignment_config_presets WHERE class_id = ?", (class_id,))

    class_entry = {}
    for assignment_name, cfg in assignments.items():
        raw_rigs = cfg.get("rigs", [])
        camera = bool(cfg.get("camera", False))
        # An empty filename here silently breaks the dashboard's saved-version
        # scan for the whole section -- default it to the assignment name, the
        # same key GAA Save uses for scene filenames.
        filename = (cfg.get("filename") or "").strip() or assignment_name
        frame_start = cfg.get("frame_start")
        frame_end = cfg.get("frame_end")
        frame_start = int(frame_start) if frame_start not in (None, "") else None
        frame_end = int(frame_end) if frame_end not in (None, "") else None
        starter_scene = (cfg.get("starter_scene") or "").strip() or None

        # Normalize rigs -- always list of { "path": "..." }, same as
        # save_assignment_config_semester()'s flattening.
        rigs = []
        for r in raw_rigs:
            if isinstance(r, str):
                rigs.append({"path": r})
            elif isinstance(r, dict):
                rig_path = r
                while isinstance(rig_path, dict) and "path" in rig_path:
                    rig_path = rig_path["path"]
                if isinstance(rig_path, str):
                    rigs.append({"path": rig_path})

        class_entry[assignment_name] = {
            "rigs": rigs,
            "camera": camera,
            "filename": filename,
            "frame_start": frame_start,
            "frame_end": frame_end,
            "starter_scene": starter_scene or ""
        }

        cursor.execute("""
            INSERT INTO assignment_config_presets (class_id, assignment_name, rigs, camera, filename, frame_start, frame_end, starter_scene)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (class_id, assignment_name, json.dumps(rigs), camera, filename, frame_start, frame_end, starter_scene))

    conn.commit()

    def merge_and_write(path):
        existing = {"semester": {"name": semester_name}}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded.get("semester"), dict):
                    existing = loaded
            except (OSError, ValueError):
                pass
        existing["semester"]["name"] = semester_name
        existing["semester"][class_name] = class_entry

        dirpath = os.path.dirname(path)
        os.makedirs(dirpath, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dirpath, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    output_path = os.path.join(r"C:\Cincy\Configs", "assignments_config.json")
    merge_and_write(output_path)
    print(f"✅ Config saved for class '{class_name}' -> {output_path}")

    # Mirror to artscifs1, same reasoning as save_assignment_config_semester().
    share_warning = None
    share_path = os.path.join(r"\\artscifs1.ad.uc.edu\Departments\GAA\UC_GAA\Configs", "assignments_config.json")
    try:
        merge_and_write(share_path)
        print(f"✅ Config mirrored to {share_path}")
    except Exception as share_err:
        share_warning = f"Saved locally, but sync to share failed: {share_err}"
        print(f"⚠️ {share_warning}")

    resp = {"success": True, "path": output_path}
    if share_warning:
        resp["warning"] = share_warning
    return jsonify(resp)


@config_bp.route("/assignment-config/files", methods=["GET"])
@login_required
def list_assignment_config_files():
    # ✅ Centralized server config folder
    config_dir = r"C:\Cincy\Configs"
    files = []

    print(f"🧭 Checking config directory: {config_dir}")
    print(f"   Exists: {os.path.exists(config_dir)}")

    if os.path.exists(config_dir):
        for file in os.listdir(config_dir):
            if file.lower().endswith(".json"):
                files.append({
                    "name": file,
                    "path": f"/classes/assignment-config/load?path={file}"
                })
    else:
        print("⚠️  Config folder not found or not accessible.")

    return jsonify({"files": files})



@config_bp.route("/assignment-config/load")
@login_required
def load_assignment_config():
    from flask import request, send_file, abort

    rel_path = request.args.get("path")
    if not rel_path:
        return abort(400, description="Missing 'path' parameter.")

    # ✅ Match same server directory
    base_dir = os.path.abspath(r"C:\Cincy\Configs")

    safe_path = os.path.abspath(os.path.join(base_dir, rel_path))

    # Safety check: make sure the file is inside the correct directory
    if not safe_path.startswith(base_dir):
        return abort(403, description="Forbidden path.")

    if not os.path.isfile(safe_path):
        return abort(404, description=f"File not found: {safe_path}")

    return send_file(safe_path, mimetype="application/json")



@config_bp.route('/assignment-review-files', methods=['GET'])
@login_required
def get_review_files():
    BASE_VIDEO_DIR = "D:/Classes"
    all_assignments = {}

    for semester_folder in os.listdir(BASE_VIDEO_DIR):
        semester_path = os.path.join(BASE_VIDEO_DIR, semester_folder)
        if not os.path.isdir(semester_path):
            continue

        for class_folder in os.listdir(semester_path):
            assignments_path = os.path.join(semester_path, class_folder, "Assignments")
            if not os.path.isdir(assignments_path):
                continue

            reviewed_files = [f for f in os.listdir(assignments_path) if f.endswith("_R.webm")]
            if reviewed_files:
                key = f"{semester_folder} - {class_folder}"
                all_assignments[key] = [
                    {"file_name": f, "path": os.path.join(assignments_path, f).replace("\\", "/")}
                    for f in reviewed_files
                ]

    return jsonify({"all_assignments": all_assignments})

@config_bp.route('/rigs', methods=['GET'])
@login_required
def list_rigs():
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


@config_bp.route('/api/launcher/assignment-config', methods=['GET'])
def get_launcher_assignment_config():
    assignment_id = request.args.get('assignment_id', type=int)
    username = request.args.get('username', type=str)

    if not assignment_id or not username:
        return jsonify({"error": "Missing assignment_id or username"}), 400

    conn = get_db()

    # Get assignment + class + semester info
    row = conn.execute("""
        SELECT 
            a.id AS assignment_id,
            a.name AS assignment_name,
            c.class_name,
            s.year || '-' || s.term AS semester,
            acp.rigs,
            acp.camera,
            a.start_date,
            a.completion_date
        FROM assignments a
        JOIN classes c ON a.class_id = c.id
        JOIN semesters s ON c.semester_id = s.id
        LEFT JOIN assignment_config_presets acp 
            ON acp.class_id = c.id 
            AND acp.assignment_name = a.name
        WHERE a.id = ?
    """, (assignment_id,)).fetchone()

    if not row:
        return jsonify({"error": "Assignment not found"}), 404

    rigs = json.loads(row['rigs']) if row['rigs'] else []

    save_path = f"\\\\artscifs1.ad.uc.edu\\Departments\\GAA\\Classes\\{row['semester']}\\{row['class_name']}\\{username}"

    return jsonify({
        "assignment_id": assignment_id,
        "assignment_name": row['assignment_name'],
        "class_name": row['class_name'],
        "semester": row['semester'],
        "rigs": rigs,
        "camera": bool(row['camera']),
        "frame_start": 1,
        "frame_end": 72,
        "save_path": save_path,
        "username": username
    })

