import json
import os
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from app.database.db import get_db
from app.routes.assignments_routes import update_assignment_status_and_crossflow

launcher_bp = Blueprint("launcher", __name__, url_prefix="/classes/api/launcher")


def _resolve_content_step(db, assignment_id, step_name):
    """
    Resolves a student-facing step (Planning/Blocking/Blocking Plus/Polish,
    never the FB-/Grade- pseudo-steps in the same flow) by name, scoped to
    one assignment's step tree. Same join/filter submit-assignment already
    uses, factored out so lock/unlock/status agree with it on what counts
    as a real step.
    """
    return db.execute("""
        SELECT s.id, s.name, s.order_num
        FROM steps s
        JOIN assignments a ON s.parent_id = a.parent_step_id
        WHERE a.id = ? AND s.name = ?
          AND s.name NOT LIKE 'FB-%' AND s.name NOT LIKE 'Grade-%'
    """, (assignment_id, step_name)).fetchone()


def _resolve_owner(db, individual_assignment_id, login_name):
    """
    Looks up the (assignment_id, owning user id) for an individual
    assignment and the calling user's id, for the ownership check shared
    by lock/unlock. Returns (ia_row, user_row, error_response) -- exactly
    one of the first two pairs is None-free depending on error_response.
    """
    ia_row = db.execute(
        "SELECT assignment_id, users_id FROM individual_assignments WHERE id = ?",
        (individual_assignment_id,)
    ).fetchone()
    if not ia_row:
        return None, None, (jsonify({"error": f"individual_assignment_id {individual_assignment_id} not found"}), 404)

    user_row = db.execute(
        "SELECT id FROM users WHERE login_name = ?", (login_name,)
    ).fetchone()
    if not user_row:
        return None, None, (jsonify({"error": f"User '{login_name}' not found"}), 404)

    if user_row["id"] != ia_row["users_id"]:
        return None, None, (jsonify({"error": "You can only lock/unlock your own assignment steps"}), 403)

    return ia_row, user_row, None


# NOTE: Intentionally unauthenticated — no browser session available from launcher.py.
# Security boundary is the intranet (10.23.20.210).
# Future hardening: add X-Launcher-Key header check via LAUNCHER_API_KEY in .env

@launcher_bp.route("/class-context", methods=["GET"])
def class_context():
    class_id   = request.args.get("class_id",   type=int)
    login_name = request.args.get("login_name", type=str, default="").strip()

    if not class_id or not login_name:
        return jsonify({"error": "Missing class_id or login_name"}), 400

    db = get_db()

    # ── Class ─────────────────────────────────────────────────────────────────
    class_row = db.execute("""
        SELECT c.id, c.class_name, s.year || '-' || s.term AS semester
        FROM classes c
        JOIN semesters s ON c.semester_id = s.id
        WHERE c.id = ?
    """, (class_id,)).fetchone()
    if not class_row:
        return jsonify({"error": f"Class {class_id} not found"}), 404

    # ── User ──────────────────────────────────────────────────────────────────
    user_row = db.execute(
        "SELECT id, name, login_name FROM users WHERE login_name = ?",
        (login_name,)
    ).fetchone()
    if not user_row:
        return jsonify({"error": f"User '{login_name}' not found"}), 404

    user_id = user_row["id"]

    # ── Assignments + rig config ───────────────────────────────────────────────
    # Pulls every individual assignment for this student in this class,
    # joined to assignment_config_presets for rigs/camera/filename.
    # LEFT JOIN on presets so assignments without a config entry still appear.
    assignment_rows = db.execute("""
        SELECT
            ia.id        AS individual_assignment_id,
            a.id         AS assignment_id,
            a.name       AS assignment_name,
            acp.rigs     AS rigs_json,
            acp.camera   AS camera,
            acp.filename AS filename
        FROM individual_assignments ia
        JOIN assignments a
            ON ia.assignment_id = a.id
        LEFT JOIN assignment_config_presets acp
            ON  acp.class_id        = a.class_id
            AND acp.assignment_name = a.name
        WHERE a.class_id  = ?
          AND ia.users_id = ?
        ORDER BY a.name
    """, (class_id, user_id)).fetchall()

    if not assignment_rows:
        return jsonify({"error": "No assignments found for this student in this class"}), 404

    # ── Per-assignment: current active step ───────────────────────────────────
    assignments = []
    for row in assignment_rows:
        ia_id = row["individual_assignment_id"]

        # Lowest order_num step that is neither Approved nor Not Started.
        # That's the step the student is currently working on.
        status_row = db.execute("""
            SELECT s.name AS step_name, ias.current_status
            FROM individual_assignment_statuses ias
            JOIN steps s ON s.id = ias.step_id
            WHERE ias.individual_assignment_id = ?
              AND ias.current_status NOT IN ('Approved', 'Not Started')
            ORDER BY s.order_num ASC
            LIMIT 1
        """, (ia_id,)).fetchone()

        assignments.append({
            "individual_assignment_id": ia_id,
            "assignment_id": row["assignment_id"],
            "name":         row["assignment_name"],
            "current_step": status_row["step_name"]     if status_row else "Not Started",
            "status":       status_row["current_status"] if status_row else "Not Started",
            "rigs":         json.loads(row["rigs_json"]) if row["rigs_json"] else [],
            "camera":       bool(row["camera"]),
            "filename":     row["filename"] or row["assignment_name"]
        })

    return jsonify({
        "user": {
            "id":           user_row["id"],
            "login_name":   user_row["login_name"],
            "display_name": user_row["name"]
        },
        "class": {
            "id":       class_row["id"],
            "name":     class_row["class_name"],
            "semester": class_row["semester"]
        },
        "assignments": assignments
    })


@launcher_bp.route("/submit-assignment", methods=["POST"])
def submit_assignment():
    """
    Marks an assignment step Submitted from playblast tooling running on a
    lab machine (no browser session available there). Same trust boundary
    as class-context: intentionally unauthenticated, security boundary is
    the intranet. Exists so playblast tools never need their own direct
    database connection — they call this instead.
    """
    data = request.get_json(silent=True) or {}
    individual_assignment_id = data.get("individual_assignment_id")
    step_name = data.get("step_name")
    new_status = data.get("status", "Submitted")

    if not individual_assignment_id:
        return jsonify({"error": "Missing individual_assignment_id"}), 400

    db = get_db()

    ia_row = db.execute(
        "SELECT assignment_id FROM individual_assignments WHERE id = ?",
        (individual_assignment_id,)
    ).fetchone()
    if not ia_row:
        return jsonify({"error": f"individual_assignment_id {individual_assignment_id} not found"}), 404

    assignment_id = ia_row["assignment_id"]

    step_row = None
    if step_name:
        step_row = db.execute("""
            SELECT s.id FROM steps s
            JOIN assignments a ON s.parent_id = a.parent_step_id
            WHERE a.id = ? AND s.name = ?
              AND s.name NOT LIKE 'FB-%' AND s.name NOT LIKE 'Grade-%'
        """, (assignment_id, step_name)).fetchone()

    if not step_row:
        # No step_name given, or it didn't match — fall back to this
        # assignment's last non-FB/Grade step (same default the playblast
        # tool has always used when no specific step was selected).
        step_row = db.execute("""
            SELECT s.id FROM steps s
            JOIN assignments a ON s.parent_id = a.parent_step_id
            WHERE a.id = ? AND s.name NOT LIKE '%FB%' AND s.name NOT LIKE '%Grade%'
            ORDER BY s.order_num DESC
            LIMIT 1
        """, (assignment_id,)).fetchone()

    if not step_row:
        return jsonify({"error": "Could not resolve a step to submit"}), 404

    step_id = step_row["id"]

    success, payload = update_assignment_status_and_crossflow(db, individual_assignment_id, step_id, new_status)
    if not success:
        return jsonify(payload), 400

    return jsonify({"success": True, "step_id": step_id, **payload})


@launcher_bp.route("/steps/lock", methods=["POST"])
def lock_step():
    """
    Locks one step of one student's individual assignment, called by the
    GAA Save shelf button when the student checks "Lock this step". Same
    unauthenticated/intranet trust boundary as class-context and
    submit-assignment -- ownership is checked against login_name instead
    of a browser session, since none exists from Maya.
    """
    data = request.get_json(silent=True) or {}
    individual_assignment_id = data.get("individual_assignment_id")
    step_name = (data.get("step_name") or "").strip()
    login_name = (data.get("login_name") or "").strip()

    if not individual_assignment_id or not step_name or not login_name:
        return jsonify({"error": "Missing individual_assignment_id, step_name, or login_name"}), 400

    db = get_db()

    ia_row, user_row, error = _resolve_owner(db, individual_assignment_id, login_name)
    if error:
        return error

    step_row = _resolve_content_step(db, ia_row["assignment_id"], step_name)
    if not step_row:
        return jsonify({"error": f"Step '{step_name}' not found for this assignment"}), 404

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    db.execute("""
        INSERT INTO step_locks (entity_type, entity_id, step_id, locked, locked_by, locked_at)
        VALUES ('assignment', ?, ?, 1, ?, ?)
        ON CONFLICT(entity_type, entity_id, step_id)
        DO UPDATE SET locked = 1, locked_by = excluded.locked_by, locked_at = excluded.locked_at
    """, (individual_assignment_id, step_row["id"], user_row["id"], now))
    db.commit()

    return jsonify({
        "success": True,
        "step_id": step_row["id"],
        "step_name": step_row["name"],
        "locked": True,
        "locked_by": login_name,
        "locked_at": now
    })


@launcher_bp.route("/steps/unlock", methods=["POST"])
def unlock_step():
    """
    Self-unlock for one step of one student's individual assignment.
    Deliberately not gated behind instructor_required/admin_required --
    the owning student can always unlock their own locked step. Still
    logs who and when via unlocked_by/unlocked_at, separate from the
    locked_by/locked_at pair so both events stay auditable.
    """
    data = request.get_json(silent=True) or {}
    individual_assignment_id = data.get("individual_assignment_id")
    step_name = (data.get("step_name") or "").strip()
    login_name = (data.get("login_name") or "").strip()

    if not individual_assignment_id or not step_name or not login_name:
        return jsonify({"error": "Missing individual_assignment_id, step_name, or login_name"}), 400

    db = get_db()

    ia_row, user_row, error = _resolve_owner(db, individual_assignment_id, login_name)
    if error:
        return error

    step_row = _resolve_content_step(db, ia_row["assignment_id"], step_name)
    if not step_row:
        return jsonify({"error": f"Step '{step_name}' not found for this assignment"}), 404

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    db.execute("""
        INSERT INTO step_locks (entity_type, entity_id, step_id, locked, unlocked_by, unlocked_at)
        VALUES ('assignment', ?, ?, 0, ?, ?)
        ON CONFLICT(entity_type, entity_id, step_id)
        DO UPDATE SET locked = 0, unlocked_by = excluded.unlocked_by, unlocked_at = excluded.unlocked_at
    """, (individual_assignment_id, step_row["id"], user_row["id"], now))
    db.commit()

    return jsonify({
        "success": True,
        "step_id": step_row["id"],
        "step_name": step_row["name"],
        "locked": False,
        "unlocked_by": login_name,
        "unlocked_at": now
    })


@launcher_bp.route("/steps/status", methods=["GET"])
def steps_status():
    """
    Live lock state for every content step (Planning/Blocking/Blocking
    Plus/Polish, never FB-/Grade-) of one individual assignment, ordered
    by order_num. Called directly by the Maya shelf tool rather than
    trusting the session JSON written at launch, since lock state can
    change mid-session.
    """
    individual_assignment_id = request.args.get("individual_assignment_id", type=int)
    if not individual_assignment_id:
        return jsonify({"error": "Missing individual_assignment_id"}), 400

    db = get_db()

    ia_row = db.execute(
        "SELECT assignment_id FROM individual_assignments WHERE id = ?",
        (individual_assignment_id,)
    ).fetchone()
    if not ia_row:
        return jsonify({"error": f"individual_assignment_id {individual_assignment_id} not found"}), 404

    rows = db.execute("""
        SELECT
            s.id AS step_id,
            s.name AS step_name,
            s.order_num,
            sc.step_code AS short_code,
            sl.locked,
            locker.login_name AS locked_by,
            sl.locked_at,
            unlocker.login_name AS unlocked_by,
            sl.unlocked_at
        FROM steps s
        JOIN assignments a ON s.parent_id = a.parent_step_id
        LEFT JOIN step_codes sc ON sc.step_name = s.name
        LEFT JOIN step_locks sl
            ON sl.entity_type = 'assignment' AND sl.entity_id = ? AND sl.step_id = s.id
        LEFT JOIN users locker ON locker.id = sl.locked_by
        LEFT JOIN users unlocker ON unlocker.id = sl.unlocked_by
        WHERE a.id = ?
          AND s.name NOT LIKE 'FB-%' AND s.name NOT LIKE 'Grade-%'
        ORDER BY s.order_num ASC
    """, (individual_assignment_id, ia_row["assignment_id"])).fetchall()

    steps = [{
        "step_id": row["step_id"],
        "name": row["step_name"],
        "short_code": row["short_code"],
        "order_num": row["order_num"],
        "locked": bool(row["locked"]),
        "locked_by": row["locked_by"],
        "locked_at": row["locked_at"],
        "unlocked_by": row["unlocked_by"],
        "unlocked_at": row["unlocked_at"],
    } for row in rows]

    return jsonify({"individual_assignment_id": individual_assignment_id, "steps": steps})


# ── Asset production (Modeling / Texture-Surface / Rigging) ───────────
# Same OPEN-button "silent, no dialogs" pattern as class assignments
# (Assignments.py's resolve_current_step over Blocking/Blocking Plus/
# Polish), applied to per-asset production steps instead. Reuses the
# already-polymorphic step_locks table with entity_type='asset_step',
# entity_id=assets.id -- see migrate_add_asset_step_codes.py.
#
# Ownership differs from assignments: an asset's Modeling/Texture/Rigging
# steps can each be assigned to a different artist
# (asset_step_assignments.assigned_user is per-step, not one owner for the
# whole asset), so lock/unlock check the specific step's assignment, not a
# single individual_assignments.users_id-style owner.

def _resolve_asset_step_owner(db, asset_id, step_name, login_name):
    step_row = db.execute("""
        SELECT s.id, s.name, asa.assigned_user
        FROM asset_step_assignments asa
        JOIN steps s ON s.id = asa.step_id
        WHERE asa.asset_id = ? AND s.name = ?
    """, (asset_id, step_name)).fetchone()
    if not step_row:
        return None, None, (jsonify({"error": f"Step '{step_name}' not found for this asset"}), 404)

    user_row = db.execute("SELECT id FROM users WHERE login_name = ?", (login_name,)).fetchone()
    if not user_row:
        return None, None, (jsonify({"error": f"User '{login_name}' not found"}), 404)

    if step_row["assigned_user"] != user_row["id"]:
        return None, None, (jsonify({"error": "You can only lock/unlock your own assigned asset steps"}), 403)

    return step_row, user_row, None


@launcher_bp.route("/asset-context", methods=["GET"])
def asset_context():
    """
    Called by launcher.py to build the Maya session JSON for the asset
    OPEN-button flow. Same unauthenticated/intranet trust boundary as
    class-context.
    """
    asset_id = request.args.get("asset_id", type=int)
    login_name = (request.args.get("login_name") or "").strip()
    # Optional: coordinator override-open from individual_assets_view.html's
    # step picker, requesting a SPECIFIC step's file regardless of lock
    # state -- see Assets.run()'s requested_step_name branch. Absent for the
    # normal student dashboard OPEN flow.
    step_name = (request.args.get("step_name") or "").strip() or None

    if not asset_id or not login_name:
        return jsonify({"error": "Missing asset_id or login_name"}), 400

    db = get_db()

    asset = db.execute("""
        SELECT a.id, a.name, a.category, a.film_id, f.name AS film_name
        FROM assets a
        JOIN films f ON f.id = a.film_id
        WHERE a.id = ?
    """, (asset_id,)).fetchone()
    if not asset:
        return jsonify({"error": f"asset_id {asset_id} not found"}), 404

    user = db.execute(
        "SELECT id, login_name, name FROM users WHERE login_name = ?", (login_name,)
    ).fetchone()
    if not user:
        return jsonify({"error": f"User '{login_name}' not found"}), 404

    return jsonify({
        "asset_id": asset["id"],
        "asset_name": asset["name"],
        "category": asset["category"],
        "film_id": asset["film_id"],
        "film_name": asset["film_name"],
        "requested_step_name": step_name,
        "user": {
            "id": user["id"],
            "login_name": user["login_name"],
            "display_name": user["name"]
        }
    })


@launcher_bp.route("/asset-steps/status", methods=["GET"])
def asset_steps_status():
    """
    Live lock state for every content step (Design/Modeling/Texture-
    Surface/Rigging/Shot Ready, never FB-prefixed) of one asset, same
    shape as steps_status() so Assets.py's resolve_current_step() (ported
    from Assignments.py) works unmodified against either.
    """
    asset_id = request.args.get("asset_id", type=int)
    if not asset_id:
        return jsonify({"error": "Missing asset_id"}), 400

    db = get_db()

    asset_row = db.execute("SELECT id FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if not asset_row:
        return jsonify({"error": f"asset_id {asset_id} not found"}), 404

    rows = db.execute("""
        SELECT
            s.id AS step_id,
            s.name AS step_name,
            s.order_num,
            sc.step_code AS short_code,
            sl.locked,
            locker.login_name AS locked_by,
            sl.locked_at,
            unlocker.login_name AS unlocked_by,
            sl.unlocked_at
        FROM asset_step_assignments asa
        JOIN steps s ON s.id = asa.step_id
        LEFT JOIN step_codes sc ON sc.step_name = s.name
        LEFT JOIN step_locks sl
            ON sl.entity_type = 'asset_step' AND sl.entity_id = ? AND sl.step_id = s.id
        LEFT JOIN users locker ON locker.id = sl.locked_by
        LEFT JOIN users unlocker ON unlocker.id = sl.unlocked_by
        WHERE asa.asset_id = ?
          AND s.name NOT LIKE 'FB %' AND s.name NOT LIKE 'Grade %'
        ORDER BY s.order_num ASC
    """, (asset_id, asset_id)).fetchall()

    steps = [{
        "step_id": row["step_id"],
        "name": row["step_name"],
        "short_code": row["short_code"],
        "order_num": row["order_num"],
        "locked": bool(row["locked"]),
        "locked_by": row["locked_by"],
        "locked_at": row["locked_at"],
        "unlocked_by": row["unlocked_by"],
        "unlocked_at": row["unlocked_at"],
    } for row in rows]

    return jsonify({"asset_id": asset_id, "steps": steps})


@launcher_bp.route("/asset-steps/lock", methods=["POST"])
def lock_asset_step():
    data = request.get_json(silent=True) or {}
    asset_id = data.get("asset_id")
    step_name = (data.get("step_name") or "").strip()
    login_name = (data.get("login_name") or "").strip()

    if not asset_id or not step_name or not login_name:
        return jsonify({"error": "Missing asset_id, step_name, or login_name"}), 400

    db = get_db()

    step_row, user_row, error = _resolve_asset_step_owner(db, asset_id, step_name, login_name)
    if error:
        return error

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    db.execute("""
        INSERT INTO step_locks (entity_type, entity_id, step_id, locked, locked_by, locked_at)
        VALUES ('asset_step', ?, ?, 1, ?, ?)
        ON CONFLICT(entity_type, entity_id, step_id)
        DO UPDATE SET locked = 1, locked_by = excluded.locked_by, locked_at = excluded.locked_at
    """, (asset_id, step_row["id"], user_row["id"], now))
    db.commit()

    return jsonify({
        "success": True,
        "step_id": step_row["id"],
        "step_name": step_row["name"],
        "locked": True,
        "locked_by": login_name,
        "locked_at": now
    })


@launcher_bp.route("/asset-steps/unlock", methods=["POST"])
def unlock_asset_step():
    """Self-unlock, same reasoning as unlock_step() -- the assigned artist can always unlock their own step."""
    data = request.get_json(silent=True) or {}
    asset_id = data.get("asset_id")
    step_name = (data.get("step_name") or "").strip()
    login_name = (data.get("login_name") or "").strip()

    if not asset_id or not step_name or not login_name:
        return jsonify({"error": "Missing asset_id, step_name, or login_name"}), 400

    db = get_db()

    step_row, user_row, error = _resolve_asset_step_owner(db, asset_id, step_name, login_name)
    if error:
        return error

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    db.execute("""
        INSERT INTO step_locks (entity_type, entity_id, step_id, locked, unlocked_by, unlocked_at)
        VALUES ('asset_step', ?, ?, 0, ?, ?)
        ON CONFLICT(entity_type, entity_id, step_id)
        DO UPDATE SET locked = 0, unlocked_by = excluded.unlocked_by, unlocked_at = excluded.unlocked_at
    """, (asset_id, step_row["id"], user_row["id"], now))
    db.commit()

    return jsonify({
        "success": True,
        "step_id": step_row["id"],
        "step_name": step_row["name"],
        "locked": False,
        "unlocked_by": login_name,
        "unlocked_at": now
    })