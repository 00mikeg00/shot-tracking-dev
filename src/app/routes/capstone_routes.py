# capstone_routes.py
# Phase 5: launcher-facing API for the capstone film pipeline (scene-level
# Layout today; shot-level Layout/Animation/Lighting land in later
# deliverables). Same unauthenticated/intranet trust boundary as
# launcher_routes.py -- called from launcher.py and Maya tooling on lab
# machines, which have no browser session. Ownership is checked against
# login_name/film_crew membership instead.

from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from app.database.db import get_db

capstone_bp = Blueprint("capstone", __name__, url_prefix="/classes/api/launcher/capstone")

SCENE_ASSET_CATEGORIES = ("Sets", "Character/Rigs")


def _resolve_scene(db, scene_id):
    return db.execute("""
        SELECT sc.id AS scene_id, sc.scene_number, sc.film_id,
               f.name AS film_name, f.step_id AS film_step_id
        FROM scenes sc
        JOIN films f ON f.id = sc.film_id
        WHERE sc.id = ?
    """, (scene_id,)).fetchone()


def _resolve_layout_step(db, film_step_id):
    return _resolve_step_by_name(db, film_step_id, "Layout")


def _resolve_step_by_name(db, film_step_id, step_name):
    return db.execute(
        "SELECT id, name FROM steps WHERE parent_id = ? AND name = ?",
        (film_step_id, step_name)
    ).fetchone()


def _resolve_shot(db, shot_id):
    return db.execute("""
        SELECT sh.id AS shot_id, sh.shot_number,
               sc.id AS scene_id, sc.scene_number, sc.film_id,
               f.name AS film_name, f.step_id AS film_step_id
        FROM shots sh
        JOIN scenes sc ON sc.id = sh.scene_id
        JOIN films f ON f.id = sc.film_id
        WHERE sh.id = ?
    """, (shot_id,)).fetchone()


def _resolve_crew_member(db, film_id, login_name):
    """
    Returns the user row if login_name is any film_crew member for this
    film (Artist/Director/Coordinator/etc -- scenes have no per-user
    assignment column the way shots do, so crew membership is the
    ownership boundary for scene-level Layout), else None.
    """
    return db.execute("""
        SELECT u.id, u.login_name, u.name
        FROM film_crew fc
        JOIN users u ON u.id = fc.user_id
        WHERE fc.film_id = ? AND u.login_name = ?
        LIMIT 1
    """, (film_id, login_name)).fetchone()


def _resolve_coordinator(db, film_id, login_name):
    """
    Returns the user row if login_name is a film_crew member for this film
    in a permission_level >= 2 role (UPM/Coordinator/Admin -- the
    supervisory film-crew groups, section='films'). Approving a shot step
    is a supervisory action, unlike scene-level Layout's student
    self-mark-done, so this is a stricter check than _resolve_crew_member.
    Note: 'Director' is permission_level 1 in the current groups table,
    same tier as 'Artist' -- so a Director alone won't pass this check
    today. Flagging rather than silently special-casing it.
    """
    return db.execute("""
        SELECT u.id, u.login_name, u.name
        FROM film_crew fc
        JOIN users u ON u.id = fc.user_id
        JOIN groups g ON g.id = fc.group_id
        WHERE fc.film_id = ? AND u.login_name = ? AND g.permission_level >= 2
        LIMIT 1
    """, (film_id, login_name)).fetchone()


def _approve_shot_step(db, shot, step_name, user):
    """
    Shared "approve one shot's {step_name}" transaction, used for Layout,
    Animation, and (once it lands) Lighting: locks the shot-level
    step_locks row for step_name (mirrors the BL->BP transition -- this
    step locked, the next one now reachable) and mirrors the same status
    into shot_step_assignments (both the production step and its paired FB
    step) so the existing kanban chart on the shots page reflects it too,
    without depending on the separate, not-fully-consistent crossflow
    endpoints elsewhere in films_routes.py.

    Returns (result_dict, error_response) -- exactly one is None.
    result_dict is ready to jsonify (minus "success"/"timeline_warning",
    which the caller adds).
    """
    step = _resolve_step_by_name(db, shot["film_step_id"], step_name)
    if not step:
        return None, (jsonify({"error": f"This film's workflow has no '{step_name}' step"}), 404)

    fb_step = _resolve_step_by_name(db, shot["film_step_id"], f"FB {step_name}")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for step_id in [step["id"]] + ([fb_step["id"]] if fb_step else []):
        db.execute("""
            INSERT INTO shot_step_assignments (shot_id, step_id, status)
            VALUES (?, ?, 'Approved')
            ON CONFLICT (shot_id, step_id) DO UPDATE SET status = 'Approved'
        """, (shot["shot_id"], step_id))

    db.execute("""
        INSERT INTO step_locks (entity_type, entity_id, step_id, locked, locked_by, locked_at)
        VALUES ('shot_step', ?, ?, 1, ?, ?)
        ON CONFLICT(entity_type, entity_id, step_id)
        DO UPDATE SET locked = 1, locked_by = excluded.locked_by, locked_at = excluded.locked_at
    """, (shot["shot_id"], step["id"], user["id"], now))
    db.commit()

    return {
        "shot_id": shot["shot_id"],
        "step_id": step["id"],
        "locked": True,
        "locked_by": user["login_name"],
        "locked_at": now
    }, None


def _timeline_warning(db, film_id, step_name):
    """
    Non-blocking informational comparison of "now" against this film's
    already-scheduled production_steps window for step_name (seeded from
    default_timelines.json, then editable per-film -- reading the concrete
    per-film dates here instead of re-deriving from the JSON template).
    Returns None if this film has no production_steps row for the step
    (nothing to compare against), else a short human string.
    """
    row = db.execute("""
        SELECT start_date, end_date FROM production_steps
        WHERE film_id = ? AND step_name = ?
    """, (film_id, step_name)).fetchone()
    if not row or not row["end_date"]:
        return None

    today = datetime.now().date()
    try:
        end_date = datetime.strptime(row["end_date"], "%Y-%m-%d").date()
        start_date = datetime.strptime(row["start_date"], "%Y-%m-%d").date() if row["start_date"] else None
    except ValueError:
        return None

    if start_date and today < start_date:
        days = (start_date - today).days
        return f"Ahead of schedule -- {step_name} isn't scheduled to start for {days} more day(s) ({start_date.isoformat()})."
    if today > end_date:
        days = (today - end_date).days
        return f"Behind schedule -- {step_name} was scheduled to finish {days} day(s) ago ({end_date.isoformat()})."
    return None


@capstone_bp.route("/scene-layout/context", methods=["GET"])
def scene_layout_context():
    scene_id = request.args.get("scene_id", type=int)
    login_name = (request.args.get("login_name") or "").strip()

    if not scene_id or not login_name:
        return jsonify({"error": "Missing scene_id or login_name"}), 400

    db = get_db()

    scene = _resolve_scene(db, scene_id)
    if not scene:
        return jsonify({"error": f"scene_id {scene_id} not found"}), 404

    user = _resolve_crew_member(db, scene["film_id"], login_name)
    if not user:
        return jsonify({"error": f"'{login_name}' is not film crew for this film"}), 403

    layout_step = _resolve_layout_step(db, scene["film_step_id"])
    if not layout_step:
        return jsonify({"error": "This film's workflow has no 'Layout' step"}), 404

    lock_row = db.execute("""
        SELECT sl.locked, locker.login_name AS locked_by, sl.locked_at
        FROM step_locks sl
        LEFT JOIN users locker ON locker.id = sl.locked_by
        WHERE sl.entity_type = 'scene_step' AND sl.entity_id = ? AND sl.step_id = ?
    """, (scene_id, layout_step["id"])).fetchone()

    assets = db.execute(f"""
        SELECT name, category, file_path
        FROM assets
        WHERE film_id = ? AND category IN ({','.join('?' * len(SCENE_ASSET_CATEGORIES))})
        ORDER BY category, name
    """, (scene["film_id"], *SCENE_ASSET_CATEGORIES)).fetchall()

    assets_by_category = {cat: [] for cat in SCENE_ASSET_CATEGORIES}
    for row in assets:
        assets_by_category.setdefault(row["category"], []).append({
            "name": row["name"],
            "file_path": row["file_path"]
        })

    return jsonify({
        "scene_id": scene_id,
        "film_id": scene["film_id"],
        "film_name": scene["film_name"],
        "scene_number": scene["scene_number"],
        "layout_step_id": layout_step["id"],
        "locked": bool(lock_row["locked"]) if lock_row else False,
        "locked_by": lock_row["locked_by"] if lock_row else None,
        "locked_at": lock_row["locked_at"] if lock_row else None,
        "assets": assets_by_category,
        "user": {
            "id": user["id"],
            "login_name": user["login_name"],
            "display_name": user["name"]
        }
    })


@capstone_bp.route("/scene-layout/complete", methods=["POST"])
def scene_layout_complete():
    """
    Student self-marks scene Layout done -- no instructor approval gate.
    Locks the scene-level Layout step_locks row; shot-level Layout for
    every shot in this scene checks this row (locked=1) before it will
    create a file, so this is what makes per-shot Layout reachable.
    """
    data = request.get_json(silent=True) or {}
    scene_id = data.get("scene_id")
    login_name = (data.get("login_name") or "").strip()

    if not scene_id or not login_name:
        return jsonify({"error": "Missing scene_id or login_name"}), 400

    db = get_db()

    scene = _resolve_scene(db, scene_id)
    if not scene:
        return jsonify({"error": f"scene_id {scene_id} not found"}), 404

    user = _resolve_crew_member(db, scene["film_id"], login_name)
    if not user:
        return jsonify({"error": f"'{login_name}' is not film crew for this film"}), 403

    layout_step = _resolve_layout_step(db, scene["film_step_id"])
    if not layout_step:
        return jsonify({"error": "This film's workflow has no 'Layout' step"}), 404

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    db.execute("""
        INSERT INTO step_locks (entity_type, entity_id, step_id, locked, locked_by, locked_at)
        VALUES ('scene_step', ?, ?, 1, ?, ?)
        ON CONFLICT(entity_type, entity_id, step_id)
        DO UPDATE SET locked = 1, locked_by = excluded.locked_by, locked_at = excluded.locked_at
    """, (scene_id, layout_step["id"], user["id"], now))
    db.commit()

    return jsonify({
        "success": True,
        "scene_id": scene_id,
        "step_id": layout_step["id"],
        "locked": True,
        "locked_by": login_name,
        "locked_at": now
    })


@capstone_bp.route("/shot-layout/context", methods=["GET"])
def shot_layout_context():
    shot_id = request.args.get("shot_id", type=int)
    login_name = (request.args.get("login_name") or "").strip()

    if not shot_id or not login_name:
        return jsonify({"error": "Missing shot_id or login_name"}), 400

    db = get_db()

    shot = _resolve_shot(db, shot_id)
    if not shot:
        return jsonify({"error": f"shot_id {shot_id} not found"}), 404

    user = _resolve_crew_member(db, shot["film_id"], login_name)
    if not user:
        return jsonify({"error": f"'{login_name}' is not film crew for this film"}), 403

    layout_step = _resolve_layout_step(db, shot["film_step_id"])
    if not layout_step:
        return jsonify({"error": "This film's workflow has no 'Layout' step"}), 404

    scene_lock = db.execute("""
        SELECT locked FROM step_locks
        WHERE entity_type = 'scene_step' AND entity_id = ? AND step_id = ?
    """, (shot["scene_id"], layout_step["id"])).fetchone()
    scene_layout_done = bool(scene_lock["locked"]) if scene_lock else False

    shot_lock = db.execute("""
        SELECT sl.locked, locker.login_name AS locked_by, sl.locked_at
        FROM step_locks sl
        LEFT JOIN users locker ON locker.id = sl.locked_by
        WHERE sl.entity_type = 'shot_step' AND sl.entity_id = ? AND sl.step_id = ?
    """, (shot_id, layout_step["id"])).fetchone()

    return jsonify({
        "shot_id": shot_id,
        "shot_number": shot["shot_number"],
        "scene_id": shot["scene_id"],
        "scene_number": shot["scene_number"],
        "film_id": shot["film_id"],
        "film_name": shot["film_name"],
        "layout_step_id": layout_step["id"],
        "scene_layout_done": scene_layout_done,
        "locked": bool(shot_lock["locked"]) if shot_lock else False,
        "locked_by": shot_lock["locked_by"] if shot_lock else None,
        "locked_at": shot_lock["locked_at"] if shot_lock else None,
        "user": {
            "id": user["id"],
            "login_name": user["login_name"],
            "display_name": user["name"]
        }
    })


@capstone_bp.route("/shot-layout/approve", methods=["POST"])
def shot_layout_approve():
    """Instructor/coordinator approves one shot's Layout. See _approve_shot_step()."""
    data = request.get_json(silent=True) or {}
    shot_id = data.get("shot_id")
    login_name = (data.get("login_name") or "").strip()

    if not shot_id or not login_name:
        return jsonify({"error": "Missing shot_id or login_name"}), 400

    db = get_db()

    shot = _resolve_shot(db, shot_id)
    if not shot:
        return jsonify({"error": f"shot_id {shot_id} not found"}), 404

    user = _resolve_coordinator(db, shot["film_id"], login_name)
    if not user:
        return jsonify({"error": f"'{login_name}' does not have approval rights for this film"}), 403

    result, error = _approve_shot_step(db, shot, "Layout", user)
    if error:
        return error

    return jsonify({
        "success": True,
        "timeline_warning": _timeline_warning(db, shot["film_id"], "Layout"),
        **result
    })


@capstone_bp.route("/shot-animation/context", methods=["GET"])
def shot_animation_context():
    shot_id = request.args.get("shot_id", type=int)
    login_name = (request.args.get("login_name") or "").strip()

    if not shot_id or not login_name:
        return jsonify({"error": "Missing shot_id or login_name"}), 400

    db = get_db()

    shot = _resolve_shot(db, shot_id)
    if not shot:
        return jsonify({"error": f"shot_id {shot_id} not found"}), 404

    user = _resolve_crew_member(db, shot["film_id"], login_name)
    if not user:
        return jsonify({"error": f"'{login_name}' is not film crew for this film"}), 403

    layout_step = _resolve_layout_step(db, shot["film_step_id"])
    animation_step = _resolve_step_by_name(db, shot["film_step_id"], "Animation")
    if not layout_step or not animation_step:
        return jsonify({"error": "This film's workflow is missing 'Layout' or 'Animation'"}), 404

    layout_lock = db.execute("""
        SELECT locked FROM step_locks
        WHERE entity_type = 'shot_step' AND entity_id = ? AND step_id = ?
    """, (shot_id, layout_step["id"])).fetchone()
    layout_locked = bool(layout_lock["locked"]) if layout_lock else False

    animation_lock = db.execute("""
        SELECT sl.locked, locker.login_name AS locked_by, sl.locked_at
        FROM step_locks sl
        LEFT JOIN users locker ON locker.id = sl.locked_by
        WHERE sl.entity_type = 'shot_step' AND sl.entity_id = ? AND sl.step_id = ?
    """, (shot_id, animation_step["id"])).fetchone()

    return jsonify({
        "shot_id": shot_id,
        "shot_number": shot["shot_number"],
        "scene_id": shot["scene_id"],
        "scene_number": shot["scene_number"],
        "film_id": shot["film_id"],
        "film_name": shot["film_name"],
        "animation_step_id": animation_step["id"],
        "layout_locked": layout_locked,
        "locked": bool(animation_lock["locked"]) if animation_lock else False,
        "locked_by": animation_lock["locked_by"] if animation_lock else None,
        "locked_at": animation_lock["locked_at"] if animation_lock else None,
        "user": {
            "id": user["id"],
            "login_name": user["login_name"],
            "display_name": user["name"]
        }
    })


@capstone_bp.route("/shot-animation/approve", methods=["POST"])
def shot_animation_approve():
    """Instructor/coordinator approves one shot's Animation. See _approve_shot_step()."""
    data = request.get_json(silent=True) or {}
    shot_id = data.get("shot_id")
    login_name = (data.get("login_name") or "").strip()

    if not shot_id or not login_name:
        return jsonify({"error": "Missing shot_id or login_name"}), 400

    db = get_db()

    shot = _resolve_shot(db, shot_id)
    if not shot:
        return jsonify({"error": f"shot_id {shot_id} not found"}), 404

    user = _resolve_coordinator(db, shot["film_id"], login_name)
    if not user:
        return jsonify({"error": f"'{login_name}' does not have approval rights for this film"}), 403

    result, error = _approve_shot_step(db, shot, "Animation", user)
    if error:
        return error

    return jsonify({
        "success": True,
        "timeline_warning": _timeline_warning(db, shot["film_id"], "Animation"),
        **result
    })


@capstone_bp.route("/shot-lighting/context", methods=["GET"])
def shot_lighting_context():
    shot_id = request.args.get("shot_id", type=int)
    login_name = (request.args.get("login_name") or "").strip()

    if not shot_id or not login_name:
        return jsonify({"error": "Missing shot_id or login_name"}), 400

    db = get_db()

    shot = _resolve_shot(db, shot_id)
    if not shot:
        return jsonify({"error": f"shot_id {shot_id} not found"}), 404

    user = _resolve_crew_member(db, shot["film_id"], login_name)
    if not user:
        return jsonify({"error": f"'{login_name}' is not film crew for this film"}), 403

    animation_step = _resolve_step_by_name(db, shot["film_step_id"], "Animation")
    lighting_step = _resolve_step_by_name(db, shot["film_step_id"], "Lighting")
    if not animation_step or not lighting_step:
        return jsonify({"error": "This film's workflow is missing 'Animation' or 'Lighting'"}), 404

    animation_lock = db.execute("""
        SELECT locked FROM step_locks
        WHERE entity_type = 'shot_step' AND entity_id = ? AND step_id = ?
    """, (shot_id, animation_step["id"])).fetchone()
    animation_locked = bool(animation_lock["locked"]) if animation_lock else False

    lighting_lock = db.execute("""
        SELECT sl.locked, locker.login_name AS locked_by, sl.locked_at
        FROM step_locks sl
        LEFT JOIN users locker ON locker.id = sl.locked_by
        WHERE sl.entity_type = 'shot_step' AND sl.entity_id = ? AND sl.step_id = ?
    """, (shot_id, lighting_step["id"])).fetchone()

    # Lighting rig: an external, reusable asset (like a character rig),
    # referenced in rather than copied -- so, unlike Layout's copy-in-only
    # flow, the Maya module needs this asset data from the DB, same as
    # scene-Layout's "assets" field.
    light_rigs = db.execute("""
        SELECT name, file_path FROM assets
        WHERE film_id = ? AND category = 'Light Rigs'
        ORDER BY name
    """, (shot["film_id"],)).fetchall()

    return jsonify({
        "shot_id": shot_id,
        "shot_number": shot["shot_number"],
        "scene_id": shot["scene_id"],
        "scene_number": shot["scene_number"],
        "film_id": shot["film_id"],
        "film_name": shot["film_name"],
        "lighting_step_id": lighting_step["id"],
        "animation_locked": animation_locked,
        "locked": bool(lighting_lock["locked"]) if lighting_lock else False,
        "locked_by": lighting_lock["locked_by"] if lighting_lock else None,
        "locked_at": lighting_lock["locked_at"] if lighting_lock else None,
        "light_rigs": [{"name": r["name"], "file_path": r["file_path"]} for r in light_rigs],
        "user": {
            "id": user["id"],
            "login_name": user["login_name"],
            "display_name": user["name"]
        }
    })


@capstone_bp.route("/shot-lighting/approve", methods=["POST"])
def shot_lighting_approve():
    """
    Instructor/coordinator approves one shot's Lighting. See
    _approve_shot_step(). Unlike Layout->Animation and Animation->Lighting,
    there is no next step to gate here -- Comp is out of scope for this
    phase (it isn't even a step in this film's workflow today; see 1.2/1.6
    findings), so Lighting approval is a terminal action for now.
    """
    data = request.get_json(silent=True) or {}
    shot_id = data.get("shot_id")
    login_name = (data.get("login_name") or "").strip()

    if not shot_id or not login_name:
        return jsonify({"error": "Missing shot_id or login_name"}), 400

    db = get_db()

    shot = _resolve_shot(db, shot_id)
    if not shot:
        return jsonify({"error": f"shot_id {shot_id} not found"}), 404

    user = _resolve_coordinator(db, shot["film_id"], login_name)
    if not user:
        return jsonify({"error": f"'{login_name}' does not have approval rights for this film"}), 403

    result, error = _approve_shot_step(db, shot, "Lighting", user)
    if error:
        return error

    return jsonify({
        "success": True,
        "timeline_warning": _timeline_warning(db, shot["film_id"], "Lighting"),
        **result
    })
