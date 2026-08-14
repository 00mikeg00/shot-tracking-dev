import os
import re
import subprocess
import uuid
from flask import Blueprint, request, jsonify, session
from app.database.db import get_db
from app.utils.auth_utils import login_required

video_reference_bp = Blueprint("video_reference", __name__, url_prefix="/video_reference")

# Same UNC root planning_routes.py / review_routes.py write to.
CLASS_FOLDER_ROOT = r"\\GAAAP1PRD01W\Classes"

# Same ffmpeg install review_routes.py's scene-concat route already shells
# out to -- video_converter.py's ffmpeg-python wrapper is unused dead code,
# this is the path actually proven to exist on the server.
FFMPEG_EXE = r"C:\ffmpeg\bin\ffmpeg.exe"

RAW_UPLOAD_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v"}
MAX_UPLOAD_BYTES = 300 * 1024 * 1024  # 300MB raw, pre-conversion


@video_reference_bp.before_request
def _allow_large_uploads():
    # The app-wide MAX_CONTENT_LENGTH (config.py) is 16MB, sized for form
    # posts/small files -- nowhere near enough for a phone-recorded
    # reference clip. Overriding it here (before body parsing) only
    # affects routes on this blueprint, not the rest of the app.
    request.max_content_length = MAX_UPLOAD_BYTES


def _resolve_planning_step(db, assignment_id):
    return db.execute("""
        SELECT s.id FROM steps s
        JOIN assignments a ON s.parent_id = a.parent_step_id
        WHERE a.id = ? AND s.name = 'Planning'
    """, (assignment_id,)).fetchone()


def _is_instructor_or_admin():
    roles = session.get("roles", [])
    if isinstance(roles, dict):
        roles = list(roles.values())
    return any(str(r).lower() in ("instructor", "admin") for r in (roles or []))


def _get_owning_assignment(db, individual_assignment_id):
    return db.execute("""
        SELECT ia.id, ia.assignment_id, ia.users_id,
               a.name AS assignment_name,
               c.class_name, s.year, s.term
        FROM individual_assignments ia
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN classes c ON a.class_id = c.id
        JOIN semesters s ON c.semester_id = s.id
        WHERE ia.id = ?
    """, (individual_assignment_id,)).fetchone()


def _check_owner_or_staff(ia_row):
    session_user_id = session.get("user_id")
    if str(ia_row["users_id"]) != str(session_user_id) and not _is_instructor_or_admin():
        return False
    return True


@video_reference_bp.route("/upload", methods=["POST"])
@login_required
def upload_video_reference():
    individual_assignment_id = request.form.get("individual_assignment_id")
    file = request.files.get("file")

    if not individual_assignment_id:
        return jsonify({"error": "Missing individual_assignment_id"}), 400
    if not file or not file.filename:
        return jsonify({"error": "No file provided"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in RAW_UPLOAD_EXTENSIONS:
        return jsonify({"error": f"Unsupported video type: {ext}"}), 400

    db = get_db()
    ia_row = _get_owning_assignment(db, individual_assignment_id)
    if not ia_row:
        return jsonify({"error": f"individual_assignment_id {individual_assignment_id} not found"}), 404

    if not _check_owner_or_staff(ia_row):
        return jsonify({"error": "You can only upload a video reference for your own assignment"}), 403

    if not _resolve_planning_step(db, ia_row["assignment_id"]):
        return jsonify({"error": "This assignment has no Planning step"}), 400

    session_user_id = session.get("user_id")
    user_row = db.execute("SELECT name FROM users WHERE id = ?", (session_user_id,)).fetchone()
    username = user_row["name"] if user_row else str(session_user_id)

    semester_folder = f"{ia_row['year']}-{ia_row['term']}"
    videoref_dir = os.path.join(
        CLASS_FOLDER_ROOT, semester_folder, ia_row["class_name"], "Assignments", "Planning", "VideoRef"
    )
    os.makedirs(videoref_dir, exist_ok=True)

    base_name = f"{ia_row['assignment_name']}_{username}"

    existing_count = db.execute("""
        SELECT COUNT(*) AS n FROM video_reference_files WHERE individual_assignment_id = ?
    """, (individual_assignment_id,)).fetchone()["n"]
    next_order = existing_count + 1

    # Stage the raw upload under a throwaway name so a same-named re-upload
    # never collides with itself mid-conversion; deleted once transcoded.
    raw_name = f"_raw_{uuid.uuid4().hex}{ext}"
    raw_path = os.path.join(videoref_dir, raw_name)
    file.save(raw_path)

    final_name = f"{base_name}_PL_VideoRef_{next_order:03d}.webm"
    final_path = os.path.join(videoref_dir, final_name)

    cmd = [
        FFMPEG_EXE, "-y",
        "-i", raw_path,
        "-c:v", "libvpx-vp9", "-b:v", "1M", "-cpu-used", "2",
        "-c:a", "libopus", "-b:a", "128k",
        final_path,
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if getattr(e, "stderr", None) else str(e)
        print(f"[ERROR] ffmpeg conversion failed: {stderr}")
        for cleanup_path in (raw_path, final_path):
            if os.path.exists(cleanup_path):
                os.remove(cleanup_path)
        return jsonify({"error": "Video conversion failed"}), 500
    finally:
        if os.path.exists(raw_path):
            os.remove(raw_path)

    if not os.path.exists(final_path):
        return jsonify({"error": "Video conversion did not produce an output file"}), 500

    file_path = final_path.replace("\\", "/")
    cursor = db.execute("""
        INSERT INTO video_reference_files
            (individual_assignment_id, uploaded_by_user_id, source_type, file_path, file_name, conversion_status)
        VALUES (?, ?, 'upload', ?, ?, 'done')
    """, (individual_assignment_id, session_user_id, file_path, final_name))
    db.commit()

    return jsonify({
        "message": "Uploaded and converted",
        "id": cursor.lastrowid,
        "file_name": final_name,
        "file_path": file_path,
    })


@video_reference_bp.route("/link", methods=["POST"])
@login_required
def add_video_reference_link():
    data = request.get_json(silent=True) or {}
    individual_assignment_id = data.get("individual_assignment_id")
    url = (data.get("url") or "").strip()

    if not individual_assignment_id:
        return jsonify({"error": "Missing individual_assignment_id"}), 400
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return jsonify({"error": "Please enter a valid http(s) URL"}), 400

    db = get_db()
    ia_row = _get_owning_assignment(db, individual_assignment_id)
    if not ia_row:
        return jsonify({"error": f"individual_assignment_id {individual_assignment_id} not found"}), 404

    if not _check_owner_or_staff(ia_row):
        return jsonify({"error": "You can only add a video reference for your own assignment"}), 403

    if not _resolve_planning_step(db, ia_row["assignment_id"]):
        return jsonify({"error": "This assignment has no Planning step"}), 400

    session_user_id = session.get("user_id")
    cursor = db.execute("""
        INSERT INTO video_reference_files
            (individual_assignment_id, uploaded_by_user_id, source_type, external_url, conversion_status)
        VALUES (?, ?, 'link', ?, 'done')
    """, (individual_assignment_id, session_user_id, url))
    db.commit()

    return jsonify({"message": "Link added", "id": cursor.lastrowid, "url": url})


@video_reference_bp.route("/list/<int:individual_assignment_id>", methods=["GET"])
@login_required
def list_video_references(individual_assignment_id):
    db = get_db()
    rows = db.execute("""
        SELECT id, source_type, file_path, file_name, external_url, conversion_status, uploaded_at
        FROM video_reference_files
        WHERE individual_assignment_id = ?
        ORDER BY uploaded_at ASC
    """, (individual_assignment_id,)).fetchall()

    return jsonify({"files": [dict(r) for r in rows]})


@video_reference_bp.route("/<int:video_reference_id>", methods=["DELETE"])
@login_required
def delete_video_reference(video_reference_id):
    db = get_db()

    row = db.execute("""
        SELECT vr.id, vr.file_path, vr.source_type, vr.individual_assignment_id,
               ia.users_id
        FROM video_reference_files vr
        JOIN individual_assignments ia ON vr.individual_assignment_id = ia.id
        WHERE vr.id = ?
    """, (video_reference_id,)).fetchone()

    if not row:
        return jsonify({"error": "Video reference not found"}), 404

    session_user_id = session.get("user_id")
    is_owner = str(row["users_id"]) == str(session_user_id)
    if not is_owner and not _is_instructor_or_admin():
        return jsonify({"error": "You can only delete your own video references"}), 403

    if row["source_type"] == "upload" and row["file_path"]:
        file_path = row["file_path"].replace("/", os.sep)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError as e:
            return jsonify({"error": f"Failed to delete file: {e}"}), 500

    db.execute("DELETE FROM video_reference_files WHERE id = ?", (video_reference_id,))
    db.commit()

    return jsonify({"message": "Deleted"})
