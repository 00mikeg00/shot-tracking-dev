import base64
import binascii
import json
import os
import uuid
from flask import Blueprint, request, jsonify, session, render_template
from app.database.db import get_db
from app.utils.auth_utils import login_required

xsheet_bp = Blueprint("xsheet", __name__, url_prefix="/xsheet")

# Same UNC root planning_routes.py / video_reference_routes.py write to.
CLASS_FOLDER_ROOT = r"\\GAAAP1PRD01W\Classes"

PHONEMES = ["AH", "EH", "EE", "IH", "OH", "EWW", "MBP", "FV", "L", "SH", "TH", "SS", "rest/closed"]

BREAKDOWN_TWEEN_VALUES = {"", "BRK", "TW"}
SYMBOL_TYPES = {"hold", "accent"}
SYMBOL_DIRECTIONS = {"up", "down", "settle"}

# The 6 columns every x-sheet starts with. Frame/Words/Sounds/Blocking are
# fully locked (can't be renamed or removed); Breakdown/Tween and Notes are
# always present by default but aren't in the hard-locked set -- Notes'
# "exactly 1" cap is enforced separately by category, not by this flag.
DEFAULT_COLUMNS = [
    ("frame", "Frame", "frame", 0, 1),
    ("words", "Words", "words", 1, 1),
    ("sounds", "Sounds", "sounds", 2, 1),
    ("blocking", "Blocking", "blocking", 3, 1),
    ("breakdown_tween", "Breakdown/Tween", "breakdown_tween", 4, 0),
    ("notes", "Notes", "notes", 5, 0),
]

# Categories a student can add more instances of. Notes is deliberately
# excluded -- it's created once by _ensure_default_columns and capped at 1.
ADDABLE_CATEGORIES = {"blinks", "hands", "tail", "legs", "camera"}
LOCKED_CATEGORIES = {"frame", "words", "sounds", "blocking"}
MAX_TOTAL_COLUMNS = 10


def _is_instructor_or_admin():
    roles = session.get("roles", [])
    if isinstance(roles, dict):
        roles = list(roles.values())
    return any(str(r).lower() in ("instructor", "admin") for r in (roles or []))


def _resolve_planning_step(db, assignment_id):
    """Same gate planning_routes.py / video_reference_routes.py use --
    whether this assignment's workflow includes a Planning step at all."""
    return db.execute("""
        SELECT s.id FROM steps s
        JOIN assignments a ON s.parent_id = a.parent_step_id
        WHERE a.id = ? AND s.name = 'Planning'
    """, (assignment_id,)).fetchone()


def _get_owning_assignment(db, individual_assignment_id):
    return db.execute("""
        SELECT ia.id, ia.assignment_id, ia.users_id, ia.frame_start, ia.frame_end,
               a.name AS assignment_name, c.class_name, s.year, s.term
        FROM individual_assignments ia
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN classes c ON a.class_id = c.id
        JOIN semesters s ON c.semester_id = s.id
        WHERE ia.id = ?
    """, (individual_assignment_id,)).fetchone()


def _check_owner_or_staff(ia_row):
    session_user_id = session.get("user_id")
    return str(ia_row["users_id"]) == str(session_user_id) or _is_instructor_or_admin()


def _ensure_default_columns(db, individual_assignment_id):
    """Lazily provisions the 6 default columns the first time anyone (student
    or instructor) loads a sheet that doesn't have columns yet -- there's no
    separate 'create x-sheet' action, the sheet is implicitly created on first view."""
    existing = db.execute(
        "SELECT COUNT(*) AS n FROM xsheet_columns WHERE individual_assignment_id = ?",
        (individual_assignment_id,)
    ).fetchone()["n"]
    if existing:
        return
    for column_key, display_name, category, display_order, locked in DEFAULT_COLUMNS:
        db.execute("""
            INSERT INTO xsheet_columns
                (individual_assignment_id, column_key, display_name, category, display_order, locked)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (individual_assignment_id, column_key, display_name, category, display_order, locked))
    db.commit()


def _max_frame_in_use(db, individual_assignment_id, frame_end):
    row_max = db.execute(
        "SELECT COALESCE(MAX(frame), 0) AS m FROM xsheet_rows WHERE individual_assignment_id = ?",
        (individual_assignment_id,)
    ).fetchone()["m"]
    symbol_max = db.execute(
        "SELECT COALESCE(MAX(frame_end), 0) AS m FROM xsheet_symbols WHERE individual_assignment_id = ?",
        (individual_assignment_id,)
    ).fetchone()["m"]
    return max(frame_end or 0, row_max, symbol_max)


@xsheet_bp.route("/<int:individual_assignment_id>", methods=["GET"])
@login_required
def get_xsheet(individual_assignment_id):
    db = get_db()
    ia_row = _get_owning_assignment(db, individual_assignment_id)
    if not ia_row:
        return jsonify({"error": f"individual_assignment_id {individual_assignment_id} not found"}), 404
    if not _check_owner_or_staff(ia_row):
        return jsonify({"error": "You can only view your own X-sheet"}), 403
    if not _resolve_planning_step(db, ia_row["assignment_id"]):
        return jsonify({"error": "This assignment has no Planning step"}), 400

    _ensure_default_columns(db, individual_assignment_id)

    columns = [dict(r) for r in db.execute("""
        SELECT column_key, display_name, category, display_order, locked
        FROM xsheet_columns WHERE individual_assignment_id = ?
        ORDER BY display_order
    """, (individual_assignment_id,)).fetchall()]

    rows = [dict(r) for r in db.execute("""
        SELECT frame, data FROM xsheet_rows
        WHERE individual_assignment_id = ? ORDER BY frame
    """, (individual_assignment_id,)).fetchall()]
    for r in rows:
        r["data"] = json.loads(r["data"]) if r["data"] else {}

    symbols = [dict(r) for r in db.execute("""
        SELECT id, column_key, frame_start, frame_end, symbol_type, direction
        FROM xsheet_symbols WHERE individual_assignment_id = ?
        ORDER BY frame_start
    """, (individual_assignment_id,)).fetchall()]

    row_count = _max_frame_in_use(db, individual_assignment_id, ia_row["frame_end"])
    session_user_id = session.get("user_id")

    return jsonify({
        "individual_assignment_id": individual_assignment_id,
        "assignment_name": ia_row["assignment_name"],
        "frame_start": ia_row["frame_start"] or 1,
        "frame_end": ia_row["frame_end"],
        "row_count": row_count,
        "columns": columns,
        "rows": rows,
        "symbols": symbols,
        "phonemes": PHONEMES,
        "is_owner": str(ia_row["users_id"]) == str(session_user_id),
        "is_staff": _is_instructor_or_admin(),
    })


@xsheet_bp.route("/<int:individual_assignment_id>/view", methods=["GET"])
@login_required
def view_xsheet_page(individual_assignment_id):
    """Renders the interactive sheet page; all actual data loads client-side
    from GET /xsheet/<id> above."""
    db = get_db()
    ia_row = _get_owning_assignment(db, individual_assignment_id)
    if not ia_row:
        return render_template("error_popup.html", message="Assignment not found", level="error"), 404
    if not _check_owner_or_staff(ia_row):
        return render_template("error_popup.html",
            message="Forbidden: you can only view your own X-sheet", level="error"), 403

    return render_template("planning/xsheet.html", individual_assignment_id=individual_assignment_id)


@xsheet_bp.route("/<int:individual_assignment_id>/save", methods=["POST"])
@login_required
def save_xsheet(individual_assignment_id):
    db = get_db()
    ia_row = _get_owning_assignment(db, individual_assignment_id)
    if not ia_row:
        return jsonify({"error": f"individual_assignment_id {individual_assignment_id} not found"}), 404

    # Editing (rows/columns/symbols) is student-owned only -- instructors get
    # view + draw-only (annotate a snapshot) access, never write access here.
    session_user_id = session.get("user_id")
    if str(ia_row["users_id"]) != str(session_user_id):
        return jsonify({"error": "Only the owning student can edit this X-sheet"}), 403
    if not _resolve_planning_step(db, ia_row["assignment_id"]):
        return jsonify({"error": "This assignment has no Planning step"}), 400

    # Save must work even if the client never GET-loaded the sheet first
    # (category-based validation below depends on columns existing).
    _ensure_default_columns(db, individual_assignment_id)

    data = request.get_json(force=True, silent=True) or {}
    rows = data.get("rows", [])
    symbols = data.get("symbols", [])

    columns = {c["column_key"]: c for c in db.execute("""
        SELECT column_key, category FROM xsheet_columns WHERE individual_assignment_id = ?
    """, (individual_assignment_id,)).fetchall()}

    breakdown_keys = {k for k, c in columns.items() if c["category"] == "breakdown_tween"}
    # Sounds is the only column with Hold/Accent/Up/Down marks, alongside its
    # phoneme letters -- Blocking/Words are plain freeform text.
    sounds_keys = {k for k, c in columns.items() if c["category"] == "sounds"}
    symbol_keys = sounds_keys

    for row in rows:
        frame = row.get("frame")
        if not isinstance(frame, int):
            return jsonify({"error": f"Invalid frame number: {frame!r}"}), 400
        row_data = row.get("data") or {}
        for key in breakdown_keys:
            if key in row_data and row_data[key] not in BREAKDOWN_TWEEN_VALUES:
                return jsonify({"error": f"Frame {frame}: invalid Breakdown/Tween value '{row_data[key]}'"}), 400
        for key in sounds_keys:
            val = row_data.get(key)
            if val not in (None, "") and val not in PHONEMES:
                return jsonify({"error": f"Frame {frame}: invalid Sounds value '{val}'"}), 400

    for sym in symbols:
        symbol_type = sym.get("symbol_type")
        if symbol_type not in SYMBOL_TYPES:
            return jsonify({"error": f"Invalid symbol_type '{symbol_type}'"}), 400
        if sym.get("column_key") not in symbol_keys:
            return jsonify({"error": "Symbols may only be placed on a Sounds column"}), 400
        direction = sym.get("direction")
        if symbol_type == "hold" and direction is not None:
            return jsonify({"error": "'hold' symbols cannot have a direction"}), 400
        if symbol_type == "accent" and direction not in SYMBOL_DIRECTIONS:
            return jsonify({"error": "'accent' symbols require a direction of up/down/settle"}), 400
        fs, fe = sym.get("frame_start"), sym.get("frame_end")
        if not isinstance(fs, int) or not isinstance(fe, int) or fe < fs:
            return jsonify({"error": "Invalid symbol frame range"}), 400

    # Sounds is mutually exclusive per frame: a phoneme letter OR a symbol
    # span on that same column, never both.
    for sym in symbols:
        key = sym["column_key"]
        for row in rows:
            frame = row.get("frame")
            if sym["frame_start"] <= frame <= sym["frame_end"]:
                if (row.get("data") or {}).get(key):
                    return jsonify({
                        "error": f"Frame {frame}: column has both text and a symbol span — remove one"
                    }), 400

    try:
        db.execute("DELETE FROM xsheet_rows WHERE individual_assignment_id = ?", (individual_assignment_id,))
        for row in rows:
            db.execute("""
                INSERT INTO xsheet_rows (individual_assignment_id, frame, data)
                VALUES (?, ?, ?)
            """, (individual_assignment_id, row["frame"], json.dumps(row.get("data") or {})))

        db.execute("DELETE FROM xsheet_symbols WHERE individual_assignment_id = ?", (individual_assignment_id,))
        for sym in symbols:
            db.execute("""
                INSERT INTO xsheet_symbols
                    (individual_assignment_id, column_key, frame_start, frame_end, symbol_type, direction)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (individual_assignment_id, sym["column_key"], sym["frame_start"], sym["frame_end"],
                  sym["symbol_type"], sym.get("direction")))

        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500

    return jsonify({"message": "Saved"})


@xsheet_bp.route("/<int:individual_assignment_id>/columns", methods=["POST"])
@login_required
def update_xsheet_columns(individual_assignment_id):
    db = get_db()
    ia_row = _get_owning_assignment(db, individual_assignment_id)
    if not ia_row:
        return jsonify({"error": f"individual_assignment_id {individual_assignment_id} not found"}), 404

    session_user_id = session.get("user_id")
    if str(ia_row["users_id"]) != str(session_user_id):
        return jsonify({"error": "Only the owning student can edit columns"}), 403
    if not _resolve_planning_step(db, ia_row["assignment_id"]):
        return jsonify({"error": "This assignment has no Planning step"}), 400

    _ensure_default_columns(db, individual_assignment_id)

    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action")

    existing = [dict(r) for r in db.execute("""
        SELECT id, column_key, display_name, category, display_order, locked
        FROM xsheet_columns WHERE individual_assignment_id = ?
    """, (individual_assignment_id,)).fetchall()]

    if action == "add":
        category = data.get("category")
        if category not in ADDABLE_CATEGORIES:
            return jsonify({"error": f"Cannot add a column of category '{category}'"}), 400
        if len(existing) >= MAX_TOTAL_COLUMNS:
            return jsonify({"error": f"Cannot exceed {MAX_TOTAL_COLUMNS} total columns"}), 400

        display_name = (data.get("display_name") or category.title()).strip()
        if not display_name:
            return jsonify({"error": "display_name is required"}), 400
        column_key = f"{category}_{uuid.uuid4().hex[:8]}"
        next_order = max((c["display_order"] for c in existing), default=-1) + 1

        db.execute("""
            INSERT INTO xsheet_columns
                (individual_assignment_id, column_key, display_name, category, display_order, locked)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (individual_assignment_id, column_key, display_name, category, next_order))
        db.commit()
        return jsonify({"message": "Column added", "column_key": column_key})

    elif action == "rename":
        column_key = data.get("column_key")
        new_name = (data.get("display_name") or "").strip()
        target = next((c for c in existing if c["column_key"] == column_key), None)
        if not target:
            return jsonify({"error": "Column not found"}), 404
        if target["category"] in LOCKED_CATEGORIES:
            return jsonify({"error": "This column is locked and cannot be renamed"}), 400
        if not new_name:
            return jsonify({"error": "display_name is required"}), 400
        db.execute("""
            UPDATE xsheet_columns SET display_name = ?
            WHERE individual_assignment_id = ? AND column_key = ?
        """, (new_name, individual_assignment_id, column_key))
        db.commit()
        return jsonify({"message": "Column renamed"})

    elif action == "remove":
        column_key = data.get("column_key")
        target = next((c for c in existing if c["column_key"] == column_key), None)
        if not target:
            return jsonify({"error": "Column not found"}), 404
        # Notes isn't in LOCKED_CATEGORIES (its display_name/rename rules
        # match student-added columns) but it's still capped at exactly 1
        # and always present, so removal is blocked by category too.
        if target["category"] in LOCKED_CATEGORIES or target["category"] == "notes":
            return jsonify({"error": "This column cannot be removed"}), 400
        db.execute("""
            DELETE FROM xsheet_columns WHERE individual_assignment_id = ? AND column_key = ?
        """, (individual_assignment_id, column_key))
        db.execute("""
            DELETE FROM xsheet_symbols WHERE individual_assignment_id = ? AND column_key = ?
        """, (individual_assignment_id, column_key))
        db.commit()
        return jsonify({"message": "Column removed"})

    elif action == "reorder":
        order = data.get("column_order") or []
        existing_keys = {c["column_key"] for c in existing}
        if set(order) != existing_keys:
            return jsonify({"error": "column_order must include every existing column exactly once"}), 400
        for i, key in enumerate(order):
            db.execute("""
                UPDATE xsheet_columns SET display_order = ?
                WHERE individual_assignment_id = ? AND column_key = ?
            """, (i, individual_assignment_id, key))
        db.commit()
        return jsonify({"message": "Columns reordered"})

    return jsonify({"error": f"Unknown action '{action}'"}), 400


@xsheet_bp.route("/<int:individual_assignment_id>/snapshot", methods=["POST"])
@login_required
def create_xsheet_snapshot(individual_assignment_id):
    """'Share for Feedback' saves the captured sheet as a planning_files row --
    the exact same table/convention as hand-drawn Planning pages -- so it
    shows up in the existing Markup Sidebar and gets annotated/reviewed
    through the same save_annotations flow those already use. No bespoke
    x-sheet annotation UI needed."""
    db = get_db()
    ia_row = _get_owning_assignment(db, individual_assignment_id)
    if not ia_row:
        return jsonify({"error": f"individual_assignment_id {individual_assignment_id} not found"}), 404
    if not _check_owner_or_staff(ia_row):
        return jsonify({"error": "You can only share your own X-sheet for feedback"}), 403
    if not _resolve_planning_step(db, ia_row["assignment_id"]):
        return jsonify({"error": "This assignment has no Planning step"}), 400

    data = request.get_json(force=True, silent=True) or {}
    image_data = data.get("image_data", "")
    prefix = "data:image/png;base64,"
    if not image_data.startswith(prefix):
        return jsonify({"error": "image_data must be a base64 PNG data URL"}), 400

    try:
        png_bytes = base64.b64decode(image_data[len(prefix):])
    except binascii.Error:
        return jsonify({"error": "Malformed image_data"}), 400

    session_user_id = session.get("user_id")
    user_row = db.execute("SELECT name FROM users WHERE id = ?", (session_user_id,)).fetchone()
    username = user_row["name"] if user_row else str(session_user_id)

    semester_folder = f"{ia_row['year']}-{ia_row['term']}"
    planning_dir = os.path.join(
        CLASS_FOLDER_ROOT, semester_folder, ia_row["class_name"], "Assignments", "Planning"
    )
    os.makedirs(planning_dir, exist_ok=True)

    base_name = f"{ia_row['assignment_name']}_{username}"

    # Same page_order + version scheme as planning_routes.py's upload_drawings
    # -- shares the same counter as hand-drawn pages so ordering in the
    # Sidebar stays consistent regardless of which type was added last.
    existing_max = db.execute("""
        SELECT COALESCE(MAX(page_order), 0) AS max_order
        FROM planning_files WHERE individual_assignment_id = ?
    """, (individual_assignment_id,)).fetchone()["max_order"]
    next_order = existing_max + 1

    version = 1
    while True:
        candidate_name = f"{base_name}_XSHEET_p{next_order:03d}_v{version}.png"
        candidate_path = os.path.join(planning_dir, candidate_name)
        if not os.path.exists(candidate_path):
            break
        version += 1

    with open(candidate_path, "wb") as f:
        f.write(png_bytes)

    stored_path = candidate_path.replace("\\", "/")
    cursor = db.execute("""
        INSERT INTO planning_files
            (individual_assignment_id, uploaded_by_user_id, file_path, file_name, page_order)
        VALUES (?, ?, ?, ?, ?)
    """, (individual_assignment_id, session_user_id, stored_path, candidate_name, next_order))
    db.commit()

    return jsonify({
        "message": "Shared for feedback",
        "id": cursor.lastrowid,
        "file_name": candidate_name,
        "file_path": stored_path,
        "page_order": next_order,
    })
