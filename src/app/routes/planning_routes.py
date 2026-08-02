import os
import re
from flask import Blueprint, request, jsonify, session
from app.database.db import get_db
from app.utils.auth_utils import login_required

planning_bp = Blueprint("planning", __name__, url_prefix="/planning")

# Same UNC root the rest of the review/assignment pipeline writes to
# (review_routes.BASE_VIDEO_DIR / assignment_service.CLASS_FOLDER_ROOT).
CLASS_FOLDER_ROOT = r"\\GAAAP1PRD01W\Classes"

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_FILES_PER_UPLOAD = 40


def _resolve_planning_step(db, assignment_id):
    """Same steps.parent_id = assignments.parent_step_id join used by
    launcher_routes._resolve_content_step -- whether this assignment's
    workflow includes a Planning step at all."""
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


@planning_bp.route("/upload_drawings", methods=["POST"])
@login_required
def upload_drawings():
    individual_assignment_id = request.form.get("individual_assignment_id")
    files = request.files.getlist("files")

    if not individual_assignment_id:
        return jsonify({"error": "Missing individual_assignment_id"}), 400
    if not files:
        return jsonify({"error": "No files provided"}), 400
    if len(files) > MAX_FILES_PER_UPLOAD:
        return jsonify({"error": f"Too many files (max {MAX_FILES_PER_UPLOAD} per upload)"}), 400

    db = get_db()

    ia_row = db.execute("""
        SELECT ia.id, ia.assignment_id, ia.users_id,
               a.name AS assignment_name,
               c.class_name, s.year, s.term
        FROM individual_assignments ia
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN classes c ON a.class_id = c.id
        JOIN semesters s ON c.semester_id = s.id
        WHERE ia.id = ?
    """, (individual_assignment_id,)).fetchone()

    if not ia_row:
        return jsonify({"error": f"individual_assignment_id {individual_assignment_id} not found"}), 404

    # Ownership check -- shared lab-machine logins mean this has to be
    # tied to the Shot Tracker session user, not the OS user.
    session_user_id = session.get("user_id")
    if str(ia_row["users_id"]) != str(session_user_id) and not _is_instructor_or_admin():
        return jsonify({"error": "You can only upload drawings for your own assignment"}), 403

    # Gate: this assignment's workflow must actually include a Planning step.
    if not _resolve_planning_step(db, ia_row["assignment_id"]):
        return jsonify({"error": "This assignment has no Planning step"}), 400

    user_row = db.execute("SELECT name FROM users WHERE id = ?", (session_user_id,)).fetchone()
    username = user_row["name"] if user_row else str(session_user_id)

    semester_folder = f"{ia_row['year']}-{ia_row['term']}"
    planning_dir = os.path.join(
        CLASS_FOLDER_ROOT, semester_folder, ia_row["class_name"], "Assignments", "Planning"
    )
    os.makedirs(planning_dir, exist_ok=True)

    base_name = f"{ia_row['assignment_name']}_{username}"

    # Next page number continues from whatever's already stored for this
    # assignment, so re-uploading appends rather than overwriting order.
    existing_max = db.execute("""
        SELECT COALESCE(MAX(page_order), 0) AS max_order
        FROM planning_files WHERE individual_assignment_id = ?
    """, (individual_assignment_id,)).fetchone()["max_order"]

    saved = []
    next_order = existing_max + 1

    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue

        # Find a free version number for this page slot so re-uploads
        # don't clobber a prior drawing on disk.
        # No secure_filename() here -- base_name comes from DB values
        # (assignment name, username), not user input, and the rest of the
        # app (e.g. /review/upload_assignment) builds these filenames the
        # same unsanitized way. Running it over the whole name mangles
        # spaces into underscores, which breaks the Sidebar's assignment
        # grouping for multi-word names ("Obstacle Course" -> "Obstacle").
        version = 1
        while True:
            candidate_name = f"{base_name}_PL_p{next_order:03d}_v{version}{ext}"
            candidate_path = os.path.join(planning_dir, candidate_name)
            if not os.path.exists(candidate_path):
                break
            version += 1

        f.save(candidate_path)

        file_path = candidate_path.replace("\\", "/")
        cursor = db.execute("""
            INSERT INTO planning_files
                (individual_assignment_id, uploaded_by_user_id, file_path, file_name, page_order)
            VALUES (?, ?, ?, ?, ?)
        """, (individual_assignment_id, session_user_id, file_path, candidate_name, next_order))

        saved.append({
            "id": cursor.lastrowid,
            "file_name": candidate_name,
            "file_path": file_path,
            "page_order": next_order,
        })
        next_order += 1

    db.commit()

    if not saved:
        return jsonify({"error": "No valid image files in upload (allowed: png, jpg, jpeg)"}), 400

    return jsonify({"message": "Uploaded successfully", "files": saved})


@planning_bp.route("/list/<int:individual_assignment_id>", methods=["GET"])
@login_required
def list_drawings(individual_assignment_id):
    db = get_db()
    rows = db.execute("""
        SELECT id, file_name, file_path, page_order, uploaded_at
        FROM planning_files
        WHERE individual_assignment_id = ?
        ORDER BY page_order ASC
    """, (individual_assignment_id,)).fetchall()

    files = []
    for r in rows:
        d = dict(r)
        d["is_reviewed"] = bool(re.search(r"_R\.(png|jpe?g)$", d["file_name"], re.IGNORECASE))
        files.append(d)

    return jsonify({"files": files})


@planning_bp.route("/drawings/<int:planning_file_id>", methods=["DELETE"])
@login_required
def delete_drawing(planning_file_id):
    db = get_db()

    row = db.execute("""
        SELECT pf.id, pf.file_path, pf.file_name, pf.individual_assignment_id,
               ia.users_id
        FROM planning_files pf
        JOIN individual_assignments ia ON pf.individual_assignment_id = ia.id
        WHERE pf.id = ?
    """, (planning_file_id,)).fetchone()

    if not row:
        return jsonify({"error": "Drawing not found"}), 404

    session_user_id = session.get("user_id")
    is_owner = str(row["users_id"]) == str(session_user_id)
    is_staff = _is_instructor_or_admin()

    if not is_owner and not is_staff:
        return jsonify({"error": "You can only delete your own drawings"}), 403

    # Once a drawing's been reviewed (renamed to _R by save_annotations),
    # the owning student can no longer delete it out from under a grade --
    # only an instructor/admin can clean those up.
    is_reviewed = bool(re.search(r"_R\.(png|jpe?g)$", row["file_name"], re.IGNORECASE))
    if is_reviewed and not is_staff:
        return jsonify({"error": "This drawing has already been reviewed and can't be deleted"}), 403

    file_path = row["file_path"].replace("/", os.sep)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        json_path = os.path.splitext(file_path)[0] + ".json"
        if os.path.exists(json_path):
            os.remove(json_path)
    except OSError as e:
        return jsonify({"error": f"Failed to delete file: {e}"}), 500

    db.execute("DELETE FROM planning_files WHERE id = ?", (planning_file_id,))
    db.commit()

    return jsonify({"message": "Deleted"})
