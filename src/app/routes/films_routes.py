import os
import json
import re
import logging
import subprocess
import datetime
from collections import deque
from flask import request, redirect, url_for, flash, Blueprint, render_template, jsonify, abort, session, send_from_directory, current_app
from flask_login import current_user
from datetime import datetime, date, timezone
from app.utils.timeline_helper import build_timeline
from app.models import get_all_steps, get_all_workflows
from app.database.db import get_db
from app.utils.auth_utils import login_required
from app.utils.utils import find_matching_asset_file, ensure_asset_folder
from app.utils.render_resolution import ASPECT_RATIO_PRESETS, DEFAULT_ASPECT_RATIO
from app.models.films import (get_all_semesters,  get_users_by_group_name, get_recursive_crossflows,
    delete_film, get_all_films, add_film, seed_preproduction_steps, get_film_by_id,
    get_all_assets, get_asset_by_id, add_asset, update_asset, delete_asset, get_asset_status_summary,
    get_all_steps, get_scene_step_status, get_scene_statuses,
    get_all_workflows_flat, add_scene_step, add_scene, has_crossflows, is_preproduction_complete_for_film, get_scene_statuses, get_prepro_status
)


films_bp = Blueprint("films", __name__)
assets_bp = Blueprint("assets", __name__)

preprod_bp = Blueprint("preproduction", __name__)

# Shared step-name groupings for phase gating (prepro-done / production-
# unlocked) -- used by view_films(), edit_film_route(), and film_overview().
PREPRO_STEP_NAMES = [
    "Treatment", "Outline", "Script_Rough", "Script_Pass",
    "Locked_Script", "Voice_Record", "Story and Script"
]
PRODUCTION_STEP_NAMES = [
    "Storyboards", "FB Storyboards", "Editorial", "Layout", "FB Layout",
    "Animation", "FB Animation", "Lighting", "FB Lighting"
]

def get_all_semesters():
    conn = get_db()
    return conn.execute("SELECT * FROM semesters ORDER BY year DESC, term DESC").fetchall()


# ----------------------------------------------------------------------------------------------------------------------
# FILMS MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def _get_enriched_flows(db, film_id):
    """
    Per-film-workflow-step status: for each step tracked in
    film_step_progress, its nodes (with colors) and whichever one is
    currently selected. Shared by view_films() (to gate Scenes-unlocked/
    prepro-done) and edit_film_route() (to render the Pre-Production
    Steps status editor).
    """
    flows = db.execute("""
        SELECT s.id as step_id, s.name as step_name
        FROM film_step_progress fsp
        JOIN steps s ON fsp.step_id = s.id
        WHERE fsp.film_id = ?
    """, (film_id,)).fetchall()

    enriched_flows = []
    for flow in flows:
        step_id = flow["step_id"]

        nodes = db.execute("""
            SELECT id as node_id, name, color
            FROM nodes
            WHERE step_id = ?
            ORDER BY CAST(substr(position, instr(position, ' ') + 1) AS INTEGER)
        """, (step_id,)).fetchall()

        current = db.execute("""
            SELECT node_id FROM film_step_progress
            WHERE film_id = ? AND step_id = ?
        """, (film_id, step_id)).fetchone()

        selected_node_id = current["node_id"] if current else None
        selected_node_name = None
        for n in nodes:
            if n["node_id"] == selected_node_id:
                selected_node_name = n["name"]
                break

        enriched_flows.append({
            "step_id": step_id,
            "step_name": flow["step_name"],
            "nodes": [dict(n) for n in nodes],
            "selected_node_id": selected_node_id,
            "selected_node_name": selected_node_name
        })

    return enriched_flows


@films_bp.route("/", endpoint="view_films")
def view_films():
    films = get_all_films()
    db = get_db()

    prepro_names = PREPRO_STEP_NAMES
    production_names = PRODUCTION_STEP_NAMES
    post_names = ["Sound", "Music", "Final Edit", "Delivery"]

    for film in films:
        flow_row = db.execute(
            "SELECT name FROM steps WHERE id = ?",
            (film["step_id"],)
        ).fetchone()
        film["workflow_name"] = flow_row["name"] if flow_row else None

        enriched_flows = _get_enriched_flows(db, film["id"])

        # ------------------------------
        # Phase checks
        # ------------------------------

        # Pre-Production steps
        prepro_steps = [f for f in enriched_flows if f["step_name"] in prepro_names and f["nodes"]]
        film["prepro_done"] = bool(prepro_steps) and all(
            f.get("selected_node_name") == "Approved" for f in prepro_steps
        )
        film["prepro_unlocked"] = bool(prepro_steps)

        scene_count = db.execute(
            "SELECT COUNT(*) AS total FROM scenes WHERE film_id = ?",
            (film["id"],)
        ).fetchone()
        film["has_scenes"] = scene_count["total"] > 0

        # Production steps
        prod_steps = [f for f in enriched_flows if f["step_name"] in production_names and f["nodes"]]
        film["production_done"] = bool(prod_steps) and all(
            f.get("selected_node_name") == "Approved" for f in prod_steps
        )
        film["production_unlocked"] = film["prepro_done"] and (bool(prod_steps) or film["has_scenes"])

    unlocked_film = request.args.get("unlocked_film")

    return render_template(
    "films/films.html",
    films=films,
    unlocked_film=unlocked_film,
    prepro_names=prepro_names,
    production_names=production_names,
    post_names=post_names
)

@films_bp.route("/<int:film_id>/overview")
def film_overview(film_id):
    """
    The "main view" of one film -- overall progress at a glance
    (Pre-Production status + Production charts broken down by Scenes/
    Shots/Asset categories). This is what a film's name links to from the
    films list; Scenes/Assets are their own tabs from here.
    """
    db = get_db()

    film_row = db.execute("""
        SELECT f.*, s.term || ' ' || s.year AS semester,
               d.name AS director_name, u.name AS upm_name
        FROM films f
        LEFT JOIN semesters s ON f.semester_id = s.id
        LEFT JOIN users d ON f.director_id = d.id
        LEFT JOIN users u ON f.upm_id = u.id
        WHERE f.id = ?
    """, (film_id,)).fetchone()
    if not film_row:
        return "Film not found", 404
    film = dict(film_row)

    flow_row = db.execute("SELECT name FROM steps WHERE id = ?", (film["step_id"],)).fetchone()
    film["workflow_name"] = flow_row["name"] if flow_row else None

    enriched_flows = _get_enriched_flows(db, film_id)

    prepro_flows = [f for f in enriched_flows if f["step_name"] in PREPRO_STEP_NAMES and f["nodes"]]
    film["prepro_done"] = bool(prepro_flows) and all(
        f.get("selected_node_name") == "Approved" for f in prepro_flows
    )

    scene_count = db.execute(
        "SELECT COUNT(*) AS total FROM scenes WHERE film_id = ?", (film_id,)
    ).fetchone()
    film["has_scenes"] = scene_count["total"] > 0

    prod_flows = [f for f in enriched_flows if f["step_name"] in PRODUCTION_STEP_NAMES and f["nodes"]]
    film["production_unlocked"] = film["prepro_done"] and (bool(prod_flows) or film["has_scenes"])

    return render_template(
        "films/film_overview.html",
        film=film,
        prepro_flows=prepro_flows,
        all_films=get_all_films(),
        active_page="overview"
    )

@films_bp.route("/add", methods=["GET", "POST"])
def add_film_route():
    db = get_db()

    if request.method == "POST":
        try:
            data = {
                "name": request.form["film_name"],
                "description": request.form.get("description", ""),
                "semester_id": request.form.get("semester_id"),
                "director_id": request.form.get("director_id"),
                "upm_id": request.form.get("upm_id"),
                "step_id": request.form.get("step_id"),
                "aspect_ratio": request.form.get("aspect_ratio")
            }

            film_id = add_film(data)
            if not film_id:
                flash("Error: Failed to create film")
                return redirect(url_for("films.add_film_route"))

            # ---- SEED DEFAULT TIMELINES ONLY ----
            import datetime
            today = datetime.date.today()

            step_colors = {
                "Treatment": "#FFB347",      # orange
                "Outline": "#87CEEB",        # light blue
                "Script_Rough": "#FFD700",   # gold
                "Script_Pass": "#ADFF2F",    # green
                "Locked_Script": "#FF69B4",  # pink
                "Voice_Record": "#9370DB",   # purple

                "Storyboards": "#FF6347",    # tomato red
                "Animatic": "#32CD32",       # lime green
                "Assets": "#4682B4",         # steel blue
                "Layout": "#FFD700",         # gold
                "Animation": "#00CED1",      # dark turquoise
                "Lighting": "#8A2BE2",       # blue violet
                "Comp": "#FF8C00",           # dark orange
                "Final_Delivery": "#2E8B57", # sea green

                "Sets": "#4682B4",        # steel blue
                "BGs": "#32CD32",         # lime green
                "Characters/Rigs": "#FF69B4",  # pink
                "Props - 3D": "#FFD700",  # gold
                "Props - 2D": "#FF8C00",  # orange
                "Light Rigs": "#9370DB",  # purple
            }

            # ---- Seed Pre-Production ----
            prepro_steps = [
                "Treatment",
                "Outline",
                "Script_Rough",
                "Script_Pass",
                "Locked_Script",
                "Voice_Record"
            ]

            all_start_dates = []
            all_end_dates = []

            for i, step_name in enumerate(prepro_steps):
                start_date = today + datetime.timedelta(weeks=i)
                end_date = start_date + datetime.timedelta(weeks=1)

                all_start_dates.append(start_date)
                all_end_dates.append(end_date)

                # 1️⃣ Timeline entry with color
                db.execute("""
                    INSERT INTO preproduction_steps
                    (film_id, step_name, start_date, end_date, status, assigned_user_id, color)
                    VALUES (?, ?, ?, ?, 'Not Started', NULL, ?)
                """, (
                    film_id,
                    step_name,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    step_colors.get(step_name, "#CCCCCC")
                ))

            # ⭐ Ensure Story and Script also exists in film_step_progress (for dropdown)
            story_step = db.execute("SELECT id FROM steps WHERE name = 'Story and Script'").fetchone()
            if story_step:
                step_id = story_step["id"]
                node_row = db.execute("""
                    SELECT id FROM nodes
                    WHERE step_id = ?
                    ORDER BY CAST(substr(position, instr(position, ' ') + 1) AS INTEGER)
                    LIMIT 1
                """, (step_id,)).fetchone()
                if node_row:
                    db.execute("""
                        INSERT INTO film_step_progress (film_id, step_id, node_id)
                        VALUES (?, ?, ?)
                    """, (film_id, step_id, node_row["id"]))

            # ✅ Commit all inserts
            db.commit()



            production_steps = [
                "Storyboards", "Animatic", "Assets",
                "Layout", "Animation", "Lighting", "Comp", "Final_Delivery"
            ]

            today = datetime.date.today()

            # Get the next "Spring" semester AFTER today
            spring_semester = db.execute("""
                SELECT * FROM semesters
                WHERE term = 'Spring' AND start_date > ?
                ORDER BY start_date ASC
                LIMIT 1
            """, (today.isoformat(),)).fetchone()

            if spring_semester:
                semester_start = datetime.datetime.strptime(spring_semester["start_date"], "%Y-%m-%d").date()
                finals_date = datetime.datetime.strptime(spring_semester["end_date"], "%Y-%m-%d").date()
            else:
                # fallback (no future spring found, default to Jan-Apr next year)
                semester_start = datetime.date(today.year + 1, 1, 10)
                finals_date = datetime.date(today.year + 1, 4, 25)


            # 🔹 Get film type from the selected workflow
            workflow = db.execute("SELECT name FROM steps WHERE id = ?", (data["step_id"],)).fetchone()
            film_type = "2D"  # fallback default

            if workflow:
                if workflow["name"] == "2D Movie Flow":
                    film_type = "2D"
                elif workflow["name"] == "3D Movie Flow":
                    film_type = "3D"

            # 🔹 Build the correct timeline (2D or 3D) → returns dict with prepro, assets, production
            timelines = build_timeline(film_type, semester_start, finals_date)

            # Seed asset steps
            for step in timelines["assets"]:
                db.execute("""
                    INSERT INTO asset_steps
                    (film_id, step_name, start_date, end_date, status, assigned_user_id, color)
                    VALUES (?, ?, ?, ?, 'Not Started', NULL, ?)
                """, (
                    film_id,
                    step["step_name"],
                    step["start_date"].isoformat(),
                    step["end_date"].isoformat(),
                    step_colors.get(step["step_name"], "#CCCCCC")
                ))

            # Seed production steps
            for step in timelines["production"]:
                db.execute("""
                    INSERT INTO production_steps
                    (film_id, step_name, start_date, end_date, status, assigned_user_id, color)
                    VALUES (?, ?, ?, ?, 'Not Started', NULL, ?)
                """, (
                    film_id,
                    step["step_name"],
                    step["start_date"].isoformat(),
                    step["end_date"].isoformat(),
                    step_colors.get(step["step_name"], "#CCCCCC")
                ))


            db.commit()
            flash("Film created successfully!")
            return jsonify({"success": True, "message": "Film created successfully"})

        except Exception as e:
            db.rollback()
            print(f"Exception occurred while creating film: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    # ---- GET form data ----
    semesters = get_all_semesters()
    directors = get_users_by_group_name("Director")
    upms = get_users_by_group_name("UPM")
    workflows = db.execute("SELECT id, name FROM steps WHERE parent_id IS NULL ORDER BY name").fetchall()
    steps = [dict(row) for row in db.execute("SELECT * FROM steps").fetchall()]

    from collections import defaultdict
    grouped_steps = defaultdict(list)
    steps_map = {}
    for step in steps:
        grouped_steps[step["parent_id"]].append(step)
        steps_map[step["id"]] = step

    # ✅ Default to “Story and Script” selected
    default_step = db.execute("SELECT id FROM steps WHERE name = 'Story and Script'").fetchone()
    selected_step_ids = [default_step["id"]] if default_step else []

    return render_template(
        "films/add_film.html",
        semesters=semesters,
        directors=directors,
        upms=upms,
        workflows=workflows,
        grouped_steps=grouped_steps,
        steps_map=steps_map,
        selected_step_ids=selected_step_ids,
        aspect_ratio_presets=ASPECT_RATIO_PRESETS,
        default_aspect_ratio=DEFAULT_ASPECT_RATIO
    )

@films_bp.route("/api/child_flows/<int:step_id>", methods=["GET"])
def get_child_flows(step_id):
    conn = get_db()
    results = conn.execute("""
        SELECT id, name
        FROM steps
        WHERE parent_id = ?
        ORDER BY name
    """, (step_id,)).fetchall()
    return {"children": [dict(row) for row in results]}

@films_bp.route("/api/film_status/<int:film_id>", methods=["GET"])
def get_film_status(film_id):
    db = get_db()

    try:
        # Fetch all node IDs for this film
        result = db.execute(
            """
            SELECT node_id
            FROM film_step_progress
            WHERE film_id = ?
            """,
            (film_id,)
        ).fetchall()

        node_ids = [row["node_id"] for row in result]

        print(f"Film Status for ID {film_id}: {node_ids}")

        return jsonify(node_ids)

    except Exception as e:
        print(f"Error fetching film status for ID {film_id}: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/api/film/<int:film_id>", methods=["GET"])
def get_film_metadata(film_id):
    db = get_db()

    try:
        film = db.execute(
            """
            SELECT id, name, step_id
            FROM films
            WHERE id = ?
            """,
            (film_id,)
        ).fetchone()

        if not film:
            return jsonify({"success": False, "message": "Film not found"}), 404

        return jsonify(dict(film))

    except Exception as e:
        print(f"Error fetching film metadata for ID {film_id}: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/api/nodes/<int:step_id>")
def get_nodes_for_step(step_id):
    db = get_db()
    results = db.execute("""
        SELECT id AS node_id,
               name,
               color
        FROM nodes
        WHERE step_id = ?
        ORDER BY CAST(substr(position, instr(position, ' ') + 1) AS INTEGER)
    """, (step_id,)).fetchall()

    return jsonify([dict(row) for row in results])

@films_bp.route("/api/nodes", methods=["GET"])
def get_all_nodes():
    db = get_db()
    results = db.execute("""
        SELECT id AS node_id,
               name,
               color
        FROM nodes
        ORDER BY CAST(substr(position, instr(position, ' ') + 1) AS INTEGER)
    """).fetchall()

    return jsonify([dict(row) for row in results])

@films_bp.route('/films/<int:film_id>/edit', methods=["GET", "POST"])
def edit_film_route(film_id):
    db = get_db()

    try:
        # Fetch the existing film data
        film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
        if not film:
            return "Film not found", 404

        all_steps = db.execute("SELECT * FROM steps WHERE parent_id IS NULL ORDER BY name").fetchall()
        all_child_steps = db.execute("SELECT * FROM steps WHERE parent_id IS NOT NULL ORDER BY parent_id, order_num").fetchall()
        semesters = get_all_semesters()
        directors = get_users_by_group_name("Director")
        upms = get_users_by_group_name("UPM")

        # Pre-Production Steps status editor -- this is the only place a
        # film's pre-production steps get approved, which is what unlocks
        # Scene creation for it.
        enriched_flows = _get_enriched_flows(db, film_id)
        prepro_flows = [f for f in enriched_flows if f["step_name"] in PREPRO_STEP_NAMES and f["nodes"]]

        if request.method == "POST":
            # Update film metadata
            name = request.form["film_name"]
            description = request.form.get("description", "")
            step_id = request.form.get("step_id")
            child_step_ids = set(map(int, request.form.getlist("child_step_ids")))
            semester_id = request.form.get("semester_id")
            director_id = request.form.get("director_id")
            upm_id = request.form.get("upm_id")
            aspect_ratio = request.form.get("aspect_ratio") or DEFAULT_ASPECT_RATIO

            db.execute("""
                UPDATE films
                SET name = ?, description = ?, step_id = ?, semester_id = ?, director_id = ?, upm_id = ?, aspect_ratio = ?
                WHERE id = ?
            """, (name, description, step_id, semester_id, director_id, upm_id, aspect_ratio, film_id))

            db.commit()
            flash("[OK] Film updated successfully!")
            return redirect(url_for("films.view_films"))

        return render_template(
            "films/edit_film.html",
            edit_mode=True,
            film=film,
            steps=all_steps,
            child_steps=all_child_steps,
            semesters=semesters,
            directors=directors,
            upms=upms,
            prepro_flows=prepro_flows,
            aspect_ratio_presets=ASPECT_RATIO_PRESETS
        )

    except Exception as e:
        db.rollback()
        logging.error(f" Error updating film {film_id}: {e}")
        flash(f" Error updating film: {e}")
        return redirect(url_for("films.view_films"))

@films_bp.route("/<int:film_id>/steps/<int:step_id>/status", methods=["POST"])
def update_film_step_status(film_id, step_id):
    db = get_db()
    data = request.json
    new_status = data.get("status")

    if not new_status:
        print("âŒ No status provided in request.")
        return jsonify({"success": False, "message": "Status is required"}), 400

    try:
        cursor = db.execute("SELECT id FROM nodes WHERE id = ? OR name = ? AND step_id = ?", (new_status, new_status, step_id))
        node_row = cursor.fetchone()

        if not node_row:
            print(f"No node found for status '{new_status}' in step {step_id}")
            return jsonify({"success": False, "message": f"Invalid status: {new_status}"}), 400

        new_node_id = node_row[0]

        print(f"Updating film_step_progress: film_id={film_id}, step_id={step_id}, node_id={new_node_id}")

        result = db.execute(
            """
            UPDATE film_step_progress
            SET node_id = ?
            WHERE film_id = ? AND step_id = ?
            """,
            (new_node_id, film_id, step_id)
        )
        db.commit()

        rows_affected = result.rowcount
        print(f"[OK] Rows updated: {rows_affected}")

        if rows_affected == 0:
            print(f"âš ï¸ No matching row found for film_id={film_id}, step_id={step_id}. Inserting new row.")
            db.execute(
                """
                INSERT INTO film_step_progress (film_id, step_id, node_id)
                VALUES (?, ?, ?)
                """,
                (film_id, step_id, new_node_id)
            )
            db.commit()

        print(f"[OK] Film step status updated successfully: film_id={film_id}, step_id={step_id}, node_id={new_node_id}")
        return jsonify({"success": True, "message": "Film step status updated successfully"})

    except Exception as e:
        db.rollback()
        print(f"âŒ Exception occurred: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/<int:film_id>/delete", methods=["POST"])
def delete_film_route(film_id):
    delete_film(film_id)
    return redirect(url_for("films.view_films"))

# ----------------------------------------------------------------------------------------------------------------------
# PRE PRO MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

@films_bp.route("/api/films/<int:film_id>/timeline")
def get_timeline(film_id):
    db = get_db()

    preproduction = db.execute(
        "SELECT * FROM preproduction_steps WHERE film_id = ?", (film_id,)
    ).fetchall()

    assets = db.execute(
        "SELECT * FROM asset_steps WHERE film_id = ?", (film_id,)
    ).fetchall()
    print("DEBUG assets raw:", [dict(r) for r in assets])  # 👈 add this

    production = db.execute(
        "SELECT * FROM production_steps WHERE film_id = ?", (film_id,)
    ).fetchall()

    return jsonify({
        "preproduction": [dict(row) for row in preproduction],
        "assets": [dict(row) for row in assets],
        "production": [dict(row) for row in production]
    })

@films_bp.route("/api/films/<int:film_id>/seed-preproduction", methods=["GET", "POST"])
def seed_preproduction(film_id):
    try:
        seed_preproduction_steps(film_id)
        return {"message": f"Preproduction steps seeded for film {film_id}"}
    except Exception as e:
        import traceback
        print("❌ Error in seed_preproduction:", e)
        print(traceback.format_exc())
        return {"error": str(e)}, 500

@films_bp.route("/api/preproduction/<int:step_id>/update", methods=["POST"])
def update_preproduction_step(step_id):
    data = request.get_json()
    print("DEBUG prepro update", step_id, data)   # 👈 add this
    db = get_db()
    db.execute("""
        UPDATE preproduction_steps
        SET start_date = ?, end_date = ?
        WHERE id = ?
    """, (data.get("start_date"), data.get("end_date"), step_id))
    db.commit()
    return jsonify({"success": True})

@films_bp.route("/api/production/<int:step_id>/update", methods=["POST"])
def update_production_step(step_id):
    data = request.get_json()
    print("DEBUG update_production_step:", data)
    db = get_db()
    db.execute("""
        UPDATE production_steps
        SET start_date = ?, end_date = ?
        WHERE id = ?
    """, (data.get("start_date"), data.get("end_date"), step_id))
    db.commit()
    return jsonify({"success": True})

@films_bp.route("/api/asset-steps/<int:step_id>/update", methods=["POST"], endpoint="update_asset_steps")
def update_asset_steps(step_id):
    data = request.get_json()
    db = get_db()
    print(f"DEBUG updating film-level asset step {step_id}: {data}")
    db.execute("""
        UPDATE asset_steps
        SET start_date = ?, end_date = ?
        WHERE id = ?
    """, (data.get("start_date"), data.get("end_date"), step_id))
    db.commit()
    return jsonify({"success": True})

@films_bp.route("/<int:film_id>/timeline")
def film_timeline(film_id):
    db = get_db()
    film = db.execute("SELECT id, name FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    return render_template("films/timeline.html", film_id=film["id"], film_name=film["name"])

@films_bp.route("/edit-timelines", methods=["GET"])
def edit_timelines():
    import os, json
    json_path = os.path.join(current_app.root_path, "utils", "default_timelines.json")

    with open(json_path, "r") as f:
        timelines = json.load(f)  # already a dict, no need for loads

    return render_template("films/edit_timelines.html", timelines=timelines)

@films_bp.route("/save-timelines", methods=["POST"])
def save_timelines():
    json_path = os.path.join(current_app.root_path, "utils", "default_timelines.json")
    new_json = request.form.get("timelines")

    try:
        # validate JSON before saving
        parsed = json.loads(new_json)
    except Exception as e:
        flash(f"Invalid JSON: {e}", "error")
        return redirect(url_for("films.edit_timelines"))

    with open(json_path, "w") as f:
        f.write(json.dumps(parsed, indent=4))

    flash("✅ Timelines updated successfully!", "success")
    return redirect(url_for("films.view_films"))

# ----------------------------------------------------------------------------------------------------------------------
# SCENES MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

@films_bp.route("/<int:film_id>/scenes/add", methods=["GET", "POST"])
def add_scene_route(film_id):
    import datetime
    db = get_db()

    # Fetch the film to ensure it exists
    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    if request.method == "POST":
        # Extract scene data from the form
        scene_number = request.form.get("scene_number")
        description = request.form.get("description", "")
        start_date = request.form.get("start_date", "")
        due_date = request.form.get("due_date", "")
        include_thumbnail = request.form.get("include_thumbnail") == "on"

        scene_start = datetime.date.fromisoformat(start_date) if start_date else None

        existing = db.execute("""
            SELECT 1 FROM scenes
            WHERE film_id = ? AND scene_number = ?
        """, (film_id, scene_number)).fetchone()

        if existing:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "message": f"Scene number {scene_number} already exists."}), 400
            else:
                flash("Scene already exists.")
                return redirect(...)

        db.execute(
            "INSERT INTO scenes (film_id, scene_number, description, start_date, due_date, include_thumbnail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (film_id, scene_number, description, start_date, due_date, include_thumbnail)
        )
        scene_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Only seed thumbnails-related steps
        steps = db.execute(
            "SELECT id, name FROM steps WHERE parent_id = ? ORDER BY order_num ASC",
            (film["step_id"],)
        ).fetchall()

        for step in steps:
            name = step["name"].strip()
            if name not in ("Thumbnails", "FB Thumbnails"):
                continue

            top_node = db.execute("""
                SELECT name FROM nodes
                WHERE step_id = ?
                ORDER BY CAST(substr(position, instr(position, ' ') + 1) AS INTEGER)
                LIMIT 1
            """, (step["id"],)).fetchone()

            status = top_node["name"] if top_node else "Not Started"

            # ✅ thumbnails only have due_date = scene_start + 7 days
            step_due = scene_start + datetime.timedelta(days=7) if scene_start else None

            db.execute("""
                INSERT INTO scene_progress_steps (scene_id, step_id, status, due_date)
                VALUES (?, ?, ?, ?)
            """, (
                scene_id,
                step["id"],
                status,
                step_due.isoformat() if step_due else None
            ))

        db.commit()

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": True,
                "message": "Scene created!",
                "scene_id": scene_id
            })

        flash(f"Scene {scene_number} created successfully!")
        return redirect(url_for("films.view_scenes", film_id=film_id))

    # ---- Pre-fill with Storyboards dates ----
    storyboard = db.execute("""
        SELECT start_date, end_date
        FROM production_steps
        WHERE film_id = ? AND step_name = 'Storyboards'
    """, (film_id,)).fetchone()

    storyboard_start = storyboard["start_date"] if storyboard else ""
    storyboard_end = storyboard["end_date"] if storyboard else ""

    steps = db.execute(
        "SELECT id, name, parent_id FROM steps WHERE parent_id = ? ORDER BY order_num ASC",
        (film["step_id"],)
    ).fetchall()

    return render_template(
        "films/add_scene.html",
        film=film,
        steps=steps,
        active_page="scenes",
        storyboard_start=storyboard_start,
        storyboard_end=storyboard_end
    )

@films_bp.route("/films/<int:film_id>/scenes/add-multiple", methods=["POST"])
def add_multiple_scenes(film_id):
    import datetime
    db = get_db()
    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    prefix = request.form.get("prefix", "").strip()
    count = int(request.form.get("count", 0))
    description = request.form.get("description", "")
    start_date = request.form.get("start_date", "")
    due_date = request.form.get("due_date", "")
    include_thumbnail = request.form.get("include_thumbnail") == "on"

    scene_start = datetime.date.fromisoformat(start_date) if start_date else None

    if not prefix.isdigit() or len(prefix) != 3 or count <= 0:
        flash("Prefix must be 3 digits and count must be positive.")
        return redirect(url_for("films.view_scenes", film_id=film_id))

    start_number = int(prefix)
    added = 0

    for i in range(count):
        scene_number = f"{start_number + i * 10:03}"

        existing = db.execute(
            "SELECT 1 FROM scenes WHERE film_id = ? AND scene_number = ?",
            (film_id, scene_number)
        ).fetchone()

        if existing:
            continue

        # Insert the scene itself
        db.execute("""
            INSERT INTO scenes (film_id, scene_number, description, start_date, due_date, include_thumbnail)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (film_id, scene_number, description, start_date, due_date, include_thumbnail))

        scene_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Only seed thumbnails-related steps
        steps = db.execute("""
            SELECT id, name FROM steps
            WHERE parent_id = ? ORDER BY order_num ASC
        """, (film["step_id"],)).fetchall()

        for step in steps:
            if step["name"] not in ("Thumbnails", "FB Thumbnails"):
                continue

            node = db.execute("""
                SELECT name FROM nodes WHERE step_id = ?
                ORDER BY CAST(substr(position, instr(position, ' ') + 1) AS INTEGER)
                LIMIT 1
            """, (step["id"],)).fetchone()

            status = node["name"] if node else "Not Started"

            # ✅ thumbnails due 1 week after scene start
            step_due = scene_start + datetime.timedelta(days=7) if scene_start else None

            db.execute("""
                INSERT INTO scene_progress_steps (scene_id, step_id, status, due_date)
                VALUES (?, ?, ?, ?)
            """, (
                scene_id,
                step["id"],
                status,
                step_due.isoformat() if step_due else None
            ))

        added += 1

    db.commit()
    flash(f"Added {added} new scenes starting at {prefix}")
    return redirect(url_for("films.view_scenes", film_id=film_id))

@films_bp.route("/<int:film_id>/scenes/<int:scene_id>/edit", methods=["GET", "POST"])
def edit_scene_route(film_id, scene_id):
    db = get_db()

    scene = db.execute("SELECT * FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if not scene:
        return "Scene not found", 404

    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    parent_step_id = film["step_id"]

    all_steps = db.execute("""
        SELECT id, name, parent_id FROM steps ORDER BY parent_id, order_num
    """).fetchall()

    grouped_steps = {}
    steps_map = {}
    for step in all_steps:
        # Group steps under their parent flow
        parent_id = step["parent_id"]
        if parent_id == parent_step_id:
            if parent_id not in grouped_steps:
                grouped_steps[parent_id] = []
            grouped_steps[parent_id].append(step)

        steps_map[step["id"]] = step

    # Handle form submission
    if request.method == "POST":
        # Extract scene data from the form
        scene_number = request.form.get("scene_number")
        description = request.form.get("description", "")
        start_date = request.form.get("start_date", "")
        due_date = request.form.get("due_date", "")
        workflow_id = request.form.get("workflow_id")

        # Update the scene in the database
        db.execute("""
            UPDATE scenes
            SET scene_number = ?, description = ?, start_date = ?, due_date = ?, workflow_id = ?
            WHERE id = ?
        """, (scene_number, description, start_date, due_date, workflow_id, scene_id))

        db.commit()
        flash("ðŸŽ¬ Scene updated successfully!")
        return redirect(url_for("films.view_scenes", film_id=film_id))

    return render_template(
        "films/edit_scene.html",
        scene=scene,
        film=film,
        grouped_steps=grouped_steps,
        steps_map=steps_map
    )

@films_bp.route("/scenes/<int:scene_id>/delete", methods=["POST"])
@login_required
def delete_scene_route(scene_id):
    db = get_db()

    film_id = db.execute("SELECT film_id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if not film_id:
        print(f"No film_id found for scene_id={scene_id}")
        return redirect(url_for("films.view_films"))
    film_id = film_id["film_id"]

    # step_locks rows for this scene's shots/scene-level steps have no real
    # FK (polymorphic entity_id, see migrate_polymorphic_step_locks.py) so
    # leaving them wouldn't raise an IntegrityError, but they'd become
    # orphaned rows pointing at a deleted shot/scene -- cleaned up here
    # alongside everything that DOES have a real FK.
    db.execute("""
        DELETE FROM step_locks
        WHERE (entity_type = 'shot_step' AND entity_id IN (SELECT id FROM shots WHERE scene_id = ?))
           OR (entity_type = 'scene_step' AND entity_id = ?)
    """, (scene_id, scene_id))

    db.execute("DELETE FROM shot_step_assignments WHERE shot_id IN (SELECT id FROM shots WHERE scene_id = ?)", (scene_id,))

    # scene_assets (Edit Layout Config's Sets/Character-Rigs/Props/etc.
    # assignments) has a real FK to scenes(id) with no ON DELETE CASCADE --
    # left this out and the scene delete below fails with
    # sqlite3.IntegrityError: FOREIGN KEY constraint failed for any scene
    # that ever had assets assigned.
    db.execute("DELETE FROM scene_assets WHERE scene_id = ?", (scene_id,))

    db.execute("DELETE FROM shots WHERE scene_id = ?", (scene_id,))

    db.execute("DELETE FROM scene_progress_steps WHERE scene_id = ?", (scene_id,))

    db.execute("DELETE FROM scenes WHERE id = ?", (scene_id,))
    db.commit()

    print(f"[OK] Deleted Scene and Related Data for scene_id={scene_id}")
    return redirect(url_for("films.view_scenes", film_id=film_id))

@films_bp.route("/<int:film_id>/scenes", methods=["GET"])
def view_scenes(film_id):
    db = get_db()

    film_row = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film_row:
        return "Film not found", 404
    film = dict(film_row)

    if not film.get("step_id"):
        return "âŒ This film has no step group (step_id). Please assign one in the admin panel.", 400

    scenes = db.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM shots WHERE scene_id = s.id) AS shot_count "
        "FROM scenes s WHERE s.film_id = ? ORDER BY s.scene_number ASC",
        (film_id,)
    ).fetchall()

    steps = db.execute(
        "SELECT id, name, parent_id, order_num FROM steps WHERE parent_id = ? ORDER BY order_num ASC",
        (film["step_id"],)
    ).fetchall()

    steps_map = {step["id"]: step for step in steps}

    # Scenes whose Layout is already marked done -- greys out/relabels
    # "Mark Layout Done" so it can't be clicked twice (it's a one-way gate,
    # same as everywhere else that reads this step_locks row).
    layout_done_scene_ids = set()
    layout_step_row = db.execute(
        "SELECT id FROM steps WHERE parent_id = ? AND name = 'Layout'",
        (film["step_id"],)
    ).fetchone()
    if layout_step_row:
        layout_done_scene_ids = {
            row["entity_id"] for row in db.execute("""
                SELECT entity_id FROM step_locks
                WHERE entity_type = 'scene_step' AND step_id = ? AND locked = 1
            """, (layout_step_row["id"],)).fetchall()
        }

    artists = db.execute("""
        SELECT u.id, u.name
        FROM film_crew fc
        JOIN users u ON fc.user_id = u.id
        WHERE fc.film_id = ? AND fc.group_id = 11
        ORDER BY u.name
    """, (film_id,)).fetchall()

    artist_names = [a["name"] for a in artists]

    enriched_scenes = []
    for scene in scenes:
        scene_dict = dict(scene)

        thumb_check = db.execute("""
            SELECT st.name, sps.status
            FROM scene_progress_steps sps
            JOIN steps st ON sps.step_id = st.id
            WHERE sps.scene_id = ? AND st.name IN ('Thumbnails', 'FB Thumbnails')
        """, (scene["id"],)).fetchall()

        thumb_status_map = {row["name"]: row["status"] for row in thumb_check}

        scene_dict["thumbnails_approved"] = (
            thumb_status_map.get("Thumbnails") == "Approved" and
            thumb_status_map.get("FB Thumbnails") == "Approved"
        )

        # Scene steps
        scene_step_ids = db.execute(
            "SELECT step_id FROM scene_progress_steps WHERE scene_id = ?",
            (scene["id"],)
        ).fetchall()
        scene_step_ids = {row["step_id"] for row in scene_step_ids}

        scene_dict["steps"] = [
            {"step_id": step["id"], "step_name": step["name"]}
            for step in steps if step["id"] in scene_step_ids
        ]

        # Detailed step chart info
        step_charts = {}
        for step_id in scene_step_ids:
            row = db.execute("""
                SELECT sps.status, sps.assigned_to, sps.due_date, u.name AS assigned_name
                FROM scene_progress_steps sps
                LEFT JOIN users u ON sps.assigned_to = u.id
                WHERE sps.scene_id = ? AND sps.step_id = ?
                LIMIT 1
            """, (scene["id"], step_id)).fetchone()

            if not row:
                continue

            # Ordered nodes (by y axis from position)
            nodes = db.execute("""
                SELECT name, color
                FROM nodes
                WHERE step_id = ?
                ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INTEGER)
            """, (step_id,)).fetchall()

            step_name = steps_map[step_id]["name"]
            step_charts[step_id] = {
                "step_name": step_name,
                "status": row["status"],
                "assigned_to": row["assigned_to"],
                "assigned_name": row["assigned_name"],  # [OK] new
                "due_date": row["due_date"],
                "nodes": [{"name": n["name"], "color": n["color"]} for n in nodes]
            }


        sorted_charts = dict(
            sorted(step_charts.items(),
                   key=lambda item: (item[1]["step_name"].lower() == "fb thumbnails", item[1]["step_name"].lower()))
        )

        scene_dict["step_charts"] = sorted_charts
        scene_dict["layout_done"] = scene["id"] in layout_done_scene_ids
        enriched_scenes.append(scene_dict)

    return render_template(
        "films/view_scenes.html",
        film=film,
        film_id=film_id,
        scenes=enriched_scenes,
        steps_map=steps_map,
        all_films=get_all_films(),
        active_page="scenes",
        show_filters=True,
        film_steps=steps,
        visible_step_ids={step["id"] for step in steps},
        crew_artists=artists
    )


# ── Edit Layout Config (Phase 5 addendum) ─────────────────────────────
# Scene-scoped asset assignment (Character/Rigs, Props - 2D/3D, BGs, Light
# Rigs, Sets) + per-shot Camera Framing, authored by the Layout Coordinator
# ahead of time so CapstoneLayout.py can reference/frame everything silently
# on file open -- no in-Maya picker. See migrate_add_layout_config.py for
# the shots.camera_framing column and the "Layout Coordinator" group this
# is gated behind.

LAYOUT_CONFIG_ASSET_CATEGORIES = ("Sets", "BGs", "Character/Rigs", "Props - 3D", "Props - 2D", "Light Rigs")
CAMERA_FRAMING_OPTIONS = ("Wide", "Full", "Cowboy", "Medium", "MCU", "CU", "ECU")


def _can_edit_layout_config(db, film_id, user_id):
    """
    True if any of:
      - film crew for this film in the 'Layout Coordinator' group (the
        actual assignable permission the design doc describes), or
      - film crew for this film in an Admin (Films) role (permission_level
        >= 3) -- per-film admin override, or
      - holds a GLOBAL 'films'-section role at permission_level >= 2 in
        user_groups (UPM, any *Coordinator, Admin (Films)) -- this is the
        table session['roles']/session['permissions'] are actually built
        from at login (see auth_utils.get_user_roles/get_user_permission_level),
        and it's how roles like UPM are commonly granted app-wide rather
        than per-film via film_crew. Checking only film_crew here missed
        every user whose film access was granted this way.
    Deliberately still short of "any >=2 coordinator" for the FILM_CREW
    case specifically (Layout Coordinator must be its own grant there) --
    only the global-role path treats UPM/Coordinator as sufficient, since
    that's the existing app-wide convention for that table.
    """
    film_crew_row = db.execute("""
        SELECT 1
        FROM film_crew fc
        JOIN groups g ON g.id = fc.group_id
        WHERE fc.film_id = ? AND fc.user_id = ?
          AND (g.name = 'Layout Coordinator' OR g.permission_level >= 3)
        LIMIT 1
    """, (film_id, user_id)).fetchone()
    if film_crew_row is not None:
        return True

    global_row = db.execute("""
        SELECT 1
        FROM user_groups ug
        JOIN groups g ON g.id = ug.group_id
        WHERE ug.user_id = ? AND g.section = 'films' AND g.permission_level >= 2
        LIMIT 1
    """, (user_id,)).fetchone()
    return global_row is not None


def _layout_step_id(db, film_step_id):
    row = db.execute(
        "SELECT id FROM steps WHERE parent_id = ? AND name = 'Layout'",
        (film_step_id,)
    ).fetchone()
    return row["id"] if row else None


def _asset_stage_labels(db, asset_ids):
    """
    {asset_id: "highest stage reached" label} for the asset picker, e.g.
    "Shot Ready" or "Texture/Surface Approved". Computed from
    asset_step_assignments/steps directly (status text), not step_locks --
    Shot Ready has no FB pair of its own (its own node IS the completion
    marker), so this can't be expressed purely as "highest locked
    step_locks row" the way MOD/TEX/RIG gating is.
    """
    if not asset_ids:
        return {}

    placeholders = ",".join("?" * len(asset_ids))
    rows = db.execute(f"""
        SELECT asa.asset_id, s.name AS step_name, s.order_num, asa.status
        FROM asset_step_assignments asa
        JOIN steps s ON s.id = asa.step_id
        WHERE asa.asset_id IN ({placeholders})
        ORDER BY s.order_num ASC
    """, asset_ids).fetchall()

    by_asset = {}
    for row in rows:
        by_asset.setdefault(row["asset_id"], []).append(row)

    labels = {}
    for asset_id, steps in by_asset.items():
        shot_ready = next((r for r in steps if r["step_name"] == "Shot Ready"), None)
        if shot_ready and shot_ready["status"] == "Shot Ready":
            labels[asset_id] = "Shot Ready"
            continue

        fb_approved = [r for r in steps if r["step_name"].startswith("FB ") and r["status"] == "Approved"]
        if fb_approved:
            highest = max(fb_approved, key=lambda r: r["order_num"])
            labels[asset_id] = f"{highest['step_name'][3:]} Approved"
            continue

        in_progress = next(
            (r for r in steps if not r["step_name"].startswith("FB ") and r["step_name"] != "Shot Ready"),
            None
        )
        labels[asset_id] = in_progress["step_name"] if in_progress else "Not Started"

    return labels


@films_bp.route("/<int:film_id>/scenes/<int:scene_id>/layout-config", methods=["GET"])
@login_required
def edit_layout_config(film_id, scene_id):
    db = get_db()

    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    scene = db.execute(
        "SELECT * FROM scenes WHERE id = ? AND film_id = ?", (scene_id, film_id)
    ).fetchone()
    if not scene:
        return "Scene not found", 404

    if not _can_edit_layout_config(db, film_id, session["user_id"]):
        return render_template(
            "error_popup.html",
            message="Forbidden: Layout Coordinator access required for this film",
            level="error"
        ), 403

    layout_step_id = _layout_step_id(db, film["step_id"])
    if not layout_step_id:
        return "This film's workflow has no 'Layout' step", 400

    scene_lock = db.execute("""
        SELECT locked FROM step_locks
        WHERE entity_type = 'scene_step' AND entity_id = ? AND step_id = ?
    """, (scene_id, layout_step_id)).fetchone()
    scene_locked = bool(scene_lock["locked"]) if scene_lock else False

    # Available assets for this film, grouped by category, for the picker.
    available = db.execute("""
        SELECT id, name, category FROM assets
        WHERE film_id = ? AND category IN ({})
        ORDER BY category, name
    """.format(",".join("?" * len(LAYOUT_CONFIG_ASSET_CATEGORIES))),
        (film_id, *LAYOUT_CONFIG_ASSET_CATEGORIES)).fetchall()

    stage_labels = _asset_stage_labels(db, [row["id"] for row in available])

    assets_by_category = {cat: [] for cat in LAYOUT_CONFIG_ASSET_CATEGORIES}
    for row in available:
        assets_by_category.setdefault(row["category"], []).append(
            {"id": row["id"], "name": row["name"], "stage_label": stage_labels.get(row["id"], "Not Started")}
        )

    # Currently-assigned assets for this scene (asset_type mirrors the
    # asset's own category at assignment time -- see save_scene_assets()).
    assigned = db.execute("""
        SELECT sa.asset_id, sa.asset_type, a.name
        FROM scene_assets sa
        JOIN assets a ON a.id = sa.asset_id
        WHERE sa.scene_id = ?
    """, (scene_id,)).fetchall()

    assigned_ids_by_category = {cat: [] for cat in LAYOUT_CONFIG_ASSET_CATEGORIES}
    for row in assigned:
        assigned_ids_by_category.setdefault(row["asset_type"], []).append(row["asset_id"])

    # Shot-level Camera Framing rows -- only meaningful once shots exist.
    # Per the corrected pipeline sequence, shots are meant to exist only
    # after scene Layout is approved; this route doesn't enforce that
    # itself (shot creation is out of scope for this deliverable -- see
    # PR notes), it just shows whatever shots already exist under this
    # scene, if any.
    shots = db.execute("""
        SELECT sh.id, sh.shot_number, sh.camera_framing, sh.frame_count,
               sl.locked AS layout_locked
        FROM shots sh
        LEFT JOIN step_locks sl
          ON sl.entity_type = 'shot_step' AND sl.entity_id = sh.id AND sl.step_id = ?
        WHERE sh.scene_id = ?
        ORDER BY sh.shot_number
    """, (layout_step_id, scene_id)).fetchall()

    return render_template(
        "films/edit_layout_config.html",
        film=film,
        scene=scene,
        scene_locked=scene_locked,
        asset_categories=LAYOUT_CONFIG_ASSET_CATEGORIES,
        assets_by_category=assets_by_category,
        assigned_ids_by_category=assigned_ids_by_category,
        camera_framing_options=CAMERA_FRAMING_OPTIONS,
        shots=[dict(s) for s in shots],
    )


@films_bp.route("/<int:film_id>/scenes/<int:scene_id>/layout-config/assets", methods=["POST"])
@login_required
def save_scene_layout_assets(film_id, scene_id):
    db = get_db()

    scene = db.execute(
        "SELECT * FROM scenes WHERE id = ? AND film_id = ?", (scene_id, film_id)
    ).fetchone()
    if not scene:
        return jsonify({"error": "Scene not found"}), 404

    if not _can_edit_layout_config(db, film_id, session["user_id"]):
        return jsonify({"error": "Forbidden: Layout Coordinator access required"}), 403

    film = db.execute("SELECT step_id FROM films WHERE id = ?", (film_id,)).fetchone()
    layout_step_id = _layout_step_id(db, film["step_id"]) if film else None
    if not layout_step_id:
        return jsonify({"error": "This film's workflow has no 'Layout' step"}), 400

    scene_lock = db.execute("""
        SELECT locked FROM step_locks
        WHERE entity_type = 'scene_step' AND entity_id = ? AND step_id = ?
    """, (scene_id, layout_step_id)).fetchone()
    if scene_lock and scene_lock["locked"]:
        return jsonify({"error": "Scene Layout is already approved/done — asset assignments are locked and cannot be edited"}), 409

    data = request.get_json(silent=True) or {}
    selections = data.get("assets", {})  # {category: [asset_id, ...]}

    if not isinstance(selections, dict):
        return jsonify({"error": "Expected 'assets' to be an object of category -> [asset_id]"}), 400

    db.execute("DELETE FROM scene_assets WHERE scene_id = ?", (scene_id,))
    for category, asset_ids in selections.items():
        if category not in LAYOUT_CONFIG_ASSET_CATEGORIES:
            continue
        for asset_id in asset_ids or []:
            db.execute(
                "INSERT INTO scene_assets (scene_id, asset_id, asset_type) VALUES (?, ?, ?)",
                (scene_id, asset_id, category)
            )
    db.commit()

    return jsonify({"success": True})


@films_bp.route("/<int:film_id>/scenes/<int:scene_id>/layout-config/shots/<int:shot_id>/camera-framing", methods=["POST"])
@login_required
def save_shot_camera_framing(film_id, scene_id, shot_id):
    db = get_db()

    shot = db.execute(
        "SELECT sh.id FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id "
        "WHERE sh.id = ? AND sh.scene_id = ? AND sc.film_id = ?",
        (shot_id, scene_id, film_id)
    ).fetchone()
    if not shot:
        return jsonify({"error": "Shot not found"}), 404

    if not _can_edit_layout_config(db, film_id, session["user_id"]):
        return jsonify({"error": "Forbidden: Layout Coordinator access required"}), 403

    film = db.execute("SELECT step_id FROM films WHERE id = ?", (film_id,)).fetchone()
    layout_step_id = _layout_step_id(db, film["step_id"]) if film else None
    if not layout_step_id:
        return jsonify({"error": "This film's workflow has no 'Layout' step"}), 400

    shot_lock = db.execute("""
        SELECT locked FROM step_locks
        WHERE entity_type = 'shot_step' AND entity_id = ? AND step_id = ?
    """, (shot_id, layout_step_id)).fetchone()
    if shot_lock and shot_lock["locked"]:
        return jsonify({"error": "This shot's Layout is already approved — Camera Framing is locked and cannot be edited"}), 409

    data = request.get_json(silent=True) or {}
    framing = data.get("camera_framing")
    if framing not in CAMERA_FRAMING_OPTIONS:
        return jsonify({"error": f"camera_framing must be one of {', '.join(CAMERA_FRAMING_OPTIONS)}"}), 400

    db.execute("UPDATE shots SET camera_framing = ? WHERE id = ?", (framing, shot_id))
    db.commit()

    return jsonify({"success": True, "shot_id": shot_id, "camera_framing": framing})


@films_bp.route("/<int:film_id>/scenes/<int:scene_id>/layout-config/shots/<int:shot_id>/frame-count", methods=["POST"])
@login_required
def save_shot_frame_count(film_id, scene_id, shot_id):
    """
    Unlike Camera Framing, frame_count is NEVER locked -- it's expected to
    change over the course of production (retimes, edit changes), and every
    scene CapstoneLayout.py/CapstoneAnimation.py opens or creates for this
    shot re-applies whatever value is current at that moment (see
    set_frame_range() in both). So there's no lock check here, only the
    same Layout Coordinator permission gate as the rest of this page.
    """
    db = get_db()

    shot = db.execute(
        "SELECT sh.id FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id "
        "WHERE sh.id = ? AND sh.scene_id = ? AND sc.film_id = ?",
        (shot_id, scene_id, film_id)
    ).fetchone()
    if not shot:
        return jsonify({"error": "Shot not found"}), 404

    if not _can_edit_layout_config(db, film_id, session["user_id"]):
        return jsonify({"error": "Forbidden: Layout Coordinator access required"}), 403

    data = request.get_json(silent=True) or {}
    frame_count = data.get("frame_count")

    if frame_count is not None:
        try:
            frame_count = int(frame_count)
        except (TypeError, ValueError):
            return jsonify({"error": "frame_count must be a whole number"}), 400
        if frame_count < 1:
            return jsonify({"error": "frame_count must be at least 1"}), 400

    db.execute("UPDATE shots SET frame_count = ? WHERE id = ?", (frame_count, shot_id))
    db.commit()

    return jsonify({"success": True, "shot_id": shot_id, "frame_count": frame_count})


@films_bp.route("/<int:film_id>/scenes/<int:scene_id>/layout-config/unlock", methods=["POST"])
@login_required
def unlock_scene_layout_config(film_id, scene_id):
    """
    Reopens the scene-level asset config for editing. This flips the SAME
    step_locks row (entity_type='scene_step', step=Layout) that
    scene_layout_complete() sets in capstone_routes.py -- there's no
    separate "config lock" to invent, the asset picker and the
    scene_layout_done gate (which decides whether shot-level Layout can be
    created) are one and the same lock by design. So unlocking here also
    un-marks "scene Layout done": intentional per explicit product
    decision to allow this, not an oversight -- flagged to the caller via
    "shots_exist" in the response rather than blocked, since shots that
    already copied-in the scene Layout are NOT retroactively affected
    (their files are independent copies, see CapstoneLayout.run_shot()),
    only NEW shot-Layout creation and further scene asset edits are.
    """
    db = get_db()

    scene = db.execute(
        "SELECT * FROM scenes WHERE id = ? AND film_id = ?", (scene_id, film_id)
    ).fetchone()
    if not scene:
        return jsonify({"error": "Scene not found"}), 404

    if not _can_edit_layout_config(db, film_id, session["user_id"]):
        return jsonify({"error": "Forbidden: Layout Coordinator access required"}), 403

    film = db.execute("SELECT step_id FROM films WHERE id = ?", (film_id,)).fetchone()
    layout_step_id = _layout_step_id(db, film["step_id"]) if film else None
    if not layout_step_id:
        return jsonify({"error": "This film's workflow has no 'Layout' step"}), 400

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute("""
        UPDATE step_locks
        SET locked = 0, unlocked_by = ?, unlocked_at = ?
        WHERE entity_type = 'scene_step' AND entity_id = ? AND step_id = ?
    """, (session["user_id"], now, scene_id, layout_step_id))
    db.commit()

    shots_exist = db.execute(
        "SELECT 1 FROM shots WHERE scene_id = ? LIMIT 1", (scene_id,)
    ).fetchone() is not None

    return jsonify({"success": True, "scene_id": scene_id, "shots_exist": shots_exist})


@films_bp.route("/<int:film_id>/scenes/<int:scene_id>/layout-config/shots/<int:shot_id>/unlock", methods=["POST"])
@login_required
def unlock_shot_camera_framing(film_id, scene_id, shot_id):
    """
    Reopens one shot's Camera Framing for editing. Same caveat as
    unlock_scene_layout_config(): this flips the SAME step_locks row
    (entity_type='shot_step', step=Layout) that shot_layout_approve() sets
    in capstone_routes.py, so it also un-marks that shot's Layout as
    approved -- which in turn means shot_animation_context() will report
    layout_locked=False again. That does NOT retroactively touch an
    Animation file that already exists (CapstoneAnimation.run_shot() only
    checks layout_locked when there's no existing Animation file to open
    yet), it only blocks a brand-new Animation file from being created
    until Layout is re-approved. Allowed anyway per explicit product
    decision -- flagged in the response, not blocked.
    """
    db = get_db()

    shot = db.execute(
        "SELECT sh.id FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id "
        "WHERE sh.id = ? AND sh.scene_id = ? AND sc.film_id = ?",
        (shot_id, scene_id, film_id)
    ).fetchone()
    if not shot:
        return jsonify({"error": "Shot not found"}), 404

    if not _can_edit_layout_config(db, film_id, session["user_id"]):
        return jsonify({"error": "Forbidden: Layout Coordinator access required"}), 403

    film = db.execute("SELECT step_id FROM films WHERE id = ?", (film_id,)).fetchone()
    layout_step_id = _layout_step_id(db, film["step_id"]) if film else None
    if not layout_step_id:
        return jsonify({"error": "This film's workflow has no 'Layout' step"}), 400

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute("""
        UPDATE step_locks
        SET locked = 0, unlocked_by = ?, unlocked_at = ?
        WHERE entity_type = 'shot_step' AND entity_id = ? AND step_id = ?
    """, (session["user_id"], now, shot_id, layout_step_id))
    db.commit()

    animation_step_id_row = db.execute(
        "SELECT id FROM steps WHERE parent_id = ? AND name = 'Animation'", (film["step_id"],)
    ).fetchone()
    animation_exists = False
    if animation_step_id_row:
        animation_exists = db.execute("""
            SELECT 1 FROM step_locks
            WHERE entity_type = 'shot_step' AND entity_id = ? AND step_id = ?
        """, (shot_id, animation_step_id_row["id"])).fetchone() is not None

    return jsonify({"success": True, "shot_id": shot_id, "animation_started": animation_exists})


@films_bp.route("/api/scene_status_summary/<int:scene_id>/<int:step_id>", methods=["GET"])
def scene_status_summary(scene_id, step_id):
    db = get_db()

    status_rows = db.execute(
        """
        SELECT ssa.status AS status, n.color, COUNT(*) as count
        FROM shot_step_assignments ssa
        JOIN shots s ON ssa.shot_id = s.id
        LEFT JOIN nodes n ON n.name = ssa.status AND n.step_id = ssa.step_id
        WHERE s.scene_id = ? AND ssa.step_id = ?
        GROUP BY ssa.status, n.color
        ORDER BY count DESC
        """,
        (scene_id, step_id)
    ).fetchall()

    response = [
        {
            "label": row["status"],
            "value": row["count"],
            "color": row["color"] or "#cccccc"
        }
        for row in status_rows
    ]

    return jsonify(response)

@films_bp.route("/api/scene_progress/<int:scene_id>/<int:step_id>/update", methods=["POST"])
def update_scene_progress_step(scene_id, step_id):
    db = get_db()
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data provided"}), 400

    allowed_fields = {"status", "assigned_to", "due_date"}
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({"error": "No valid fields to update"}), 400

    if "assigned_to" in updates:
        try:
            updates["assigned_to"] = int(updates["assigned_to"])
        except (TypeError, ValueError):
            updates["assigned_to"] = None

    result = db.execute(
        f"""
        UPDATE scene_progress_steps
        SET {', '.join([f'{k} = ?' for k in updates])}
        WHERE scene_id = ? AND step_id = ?
        """,
        list(updates.values()) + [scene_id, step_id]
    )

    print(f"[OK] {result.rowcount} row(s) updated for scene_id={scene_id}, step_id={step_id}")

    if "status" in updates:
        new_status = updates["status"]
        parent_node = db.execute(
            "SELECT id FROM nodes WHERE step_id = ? AND name = ?",
            (step_id, new_status)
        ).fetchone()

        if parent_node:
            linked = db.execute("""
                SELECT step_id, child_node_id, to_flow_id
                FROM links
                WHERE parent_node_id = ? AND to_flow_id IS NOT NULL
            """, (parent_node["id"],)).fetchall()

            for row in linked:
                child_node = db.execute(
                    "SELECT name FROM nodes WHERE id = ?", (row["child_node_id"],)
                ).fetchone()
                if child_node:
                    db.execute("""
                        UPDATE scene_progress_steps
                        SET status = ?
                        WHERE scene_id = ? AND step_id = ?
                    """, (child_node["name"], scene_id, row["to_flow_id"]))

    thumb_check = db.execute("""
        SELECT st.name, sps.status
        FROM scene_progress_steps sps
        JOIN steps st ON sps.step_id = st.id
        WHERE sps.scene_id = ? AND st.name IN ('Thumbnails', 'FB Thumbnails')
    """, (scene_id,)).fetchall()

    status_map = {row["name"]: row["status"] for row in thumb_check}
    approved = (
        status_map.get("Thumbnails") == "Approved"
        and status_map.get("FB Thumbnails") == "Approved"
    )
    db.execute(
        "UPDATE scenes SET thumbnails_approved = ? WHERE id = ?",
        (1 if approved else 0, scene_id)
    )

    db.commit()
    return jsonify({"success": True, "updated": updates})

@films_bp.route("/api/scene_progress/crossflow", methods=["POST"])
def update_scene_crossflow():
    data = request.get_json()
    scene_id = data.get("scene_id")
    step_id = data.get("step_id")
    status = data.get("status")

    if not all([scene_id, step_id, status]):
        return jsonify({"error": "Missing required parameters"}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT to_flow_id
        FROM links
        WHERE step_id = ?
    """, (step_id,))
    linked_steps = cursor.fetchall()

    updated = []

    for row in linked_steps:
        to_step = row["to_flow_id"]
        cursor.execute("""
            UPDATE scene_progress_steps
            SET status = ?
            WHERE scene_id = ? AND step_id = ?
        """, (status, scene_id, to_step))
        updated.append(to_step)

    conn.commit()
    conn.close()

    return jsonify({"updated_steps": updated})

@films_bp.route("/api/get_scene_id/<string:film_name>/<string:scene_number>")
def get_scene_id(film_name, scene_number):
    """Find scene_id by film name and scene_number (with or without leading zeros)."""
    db = get_db()

    # Normalize scene_number — remove leading zeros
    normalized_scene_number = scene_number.lstrip("0") or "0"

    scene = db.execute("""
        SELECT sc.id
        FROM scenes sc
        JOIN films f ON sc.film_id = f.id
        WHERE f.name = ?
          AND (sc.scene_number = ? OR sc.scene_number = ?)
    """, (film_name, scene_number, normalized_scene_number)).fetchone()

    if scene:
        return jsonify({"scene_id": scene["id"]})
    return jsonify({"error": f"Scene not found for {film_name} scene_number {scene_number}"}), 404

@films_bp.route("/api/get_scene/<int:scene_id>")
def get_scene(scene_id):
    """Return basic info for one scene."""
    db = get_db()
    row = db.execute("""
        SELECT id, film_id, scene_number, thumbnails_approved
        FROM scenes
        WHERE id = ?
    """, (scene_id,)).fetchone()

    if row:
        return jsonify(dict(row))
    return jsonify({"error": "Not Found"}), 404

@films_bp.route("/api/get_step_id/<string:film>/<path:extra>", methods=["GET"])
def get_step_id(film, extra):
    """
    Look up a step by its short_code (SB, LAY, ANI, etc.)
    and return the corresponding step_id.
    """

    # Handle URLs like /film/030/SB  → scene = 030, step_code = SB
    parts = extra.split("/")
    if len(parts) == 2:
        scene_number, step_code = parts
    else:
        step_code = parts[0]
    db = get_db()
    step = db.execute(
        """
        SELECT id, name, short_code
        FROM steps
        WHERE short_code = ? COLLATE NOCASE
        OR name = ? COLLATE NOCASE
        """,
        (step_code, step_code),
    ).fetchone()


    if step:
        return jsonify({
            "step_id": step["id"],
            "step_name": step["name"],
            "short_code": step["short_code"]
        })

    return jsonify({"error": f"Step not found for code '{step_code}'"}), 404


# ----------------------------------------------------------------------------------------------------------------------
# SHOT MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

@films_bp.route("/api/get_shots_storyboard/<int:scene_id>")
def get_shots_storyboard(scene_id):
    """
    Returns all shots in a scene with their Storyboard (or FB Storyboards) status.
    Each row comes from shot_step_assignments joined to steps and shots.
    If a shot has no record yet, returns status 'Not Started'.
    """
    db = get_db()

    # --- Find the step_id for "Storyboards" or short_code = 'SB' ---
    step_row = db.execute("""
        SELECT id FROM steps 
        WHERE name IN ('FB Storyboards', 'Storyboards')
           OR short_code = 'SB'
        ORDER BY id DESC LIMIT 1
    """).fetchone()

    if not step_row:
        return jsonify({"error": "No Storyboard step found"}), 404
    sb_step_id = step_row["id"]

    # --- Fetch all shots and their status directly with JOIN ---
    shots = db.execute("""
        SELECT 
            s.id AS shot_id,
            s.shot_number,
            COALESCE(ssa.status, 'Not Started') AS status
        FROM shots s
        LEFT JOIN shot_step_assignments ssa
            ON ssa.shot_id = s.id AND ssa.step_id = ?
        WHERE s.scene_id = ?
        ORDER BY s.shot_number
    """, (sb_step_id, scene_id)).fetchall()

    result = [
        {
            "shot_id": row["shot_id"],
            "shot_number": row["shot_number"],
            "step_id": sb_step_id,
            "step_name": "Storyboards",
            "status": row["status"]
        }
        for row in shots
    ]

    return jsonify(result)


@films_bp.route("/api/update_storyboard_status", methods=["POST"])
def update_storyboard_status():
    """
    Updates the status of a single storyboard shot.
    Writes to shot_step_assignments table.
    """
    db = get_db()
    data = request.get_json()
    shot_id = data.get("shot_id")
    step_id = data.get("step_id")
    new_status = data.get("status")

    if not shot_id or not step_id or not new_status:
        return jsonify({"error": "Missing parameters"}), 400

    db.execute(
        """
        UPDATE shot_step_assignments
        SET status = ?
        WHERE shot_id = ? AND step_id = ?
        """,
        (new_status, shot_id, step_id),
    )
    db.commit()

    return jsonify({"success": True, "shot_id": shot_id, "step_id": step_id, "new_status": new_status})

@films_bp.route("/api/get_shots_by_scene/<int:scene_id>")
def get_shots_by_scene(scene_id):
    """Return all shots in a scene (for syncing / export tools)."""
    db = get_db()
    shots = db.execute("""
        SELECT id, shot_number, scene_id
        FROM shots
        WHERE scene_id = ?
        ORDER BY shot_number
    """, (scene_id,)).fetchall()

    if not shots:
        return jsonify({"error": f"No shots found for scene {scene_id}"}), 404

    return jsonify([dict(row) for row in shots])


@films_bp.route("/api/shot_progress/<int:shot_id>/<int:step_id>/update", methods=["POST"])
def update_shot_progress(shot_id, step_id):
    """Update status of a shot for a specific step."""
    db = get_db()
    data = request.get_json()
    new_status = data.get("status", "Submitted")

    print(f"[UPDATE] shot_id={shot_id}, step_id={step_id}, new_status={new_status}")

    # Make sure this record exists
    row = db.execute("""
        SELECT * FROM shot_step_assignments
        WHERE shot_id = ? AND step_id = ?
    """, (shot_id, step_id)).fetchone()

    if not row:
        print(f"[WARN] No record found for shot_id={shot_id}, step_id={step_id}")
        return jsonify({"error": "Record not found"}), 404

    db.execute("""
        UPDATE shot_step_assignments
        SET status = ?
        WHERE shot_id = ? AND step_id = ?
    """, (new_status, shot_id, step_id))
    db.commit()

    print(f"[OK] Updated shot {shot_id} step {step_id} to {new_status}")
    return jsonify({"message": "Shot progress updated successfully"})


@films_bp.route("/api/films/shots/<int:shot_id>/steps", methods=["GET"])
@login_required
def get_shot_steps(shot_id):
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Fetch steps for this shot, including current status
        steps = cursor.execute("""
            SELECT 
                s.id AS step_id,
                s.name AS step_name,
                n.id AS node_id,
                n.name AS node_name,
                n.color,
                ssa.current_status AS current_status
            FROM shot_step_assignments ssa
            JOIN steps s ON ssa.step_id = s.id
            LEFT JOIN nodes n ON s.id = n.step_id
            WHERE ssa.shot_id = ?
            ORDER BY s.order_num, n.position
        """, (shot_id,)).fetchall()

        # Structure the response
        step_list = []
        for row in steps:
            step = dict(row)
            step_list.append(step)

        return jsonify({"steps": step_list})

    except Exception as e:
        print(f"âŒ Error fetching shot steps: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/api/films/shots/<int:shot_id>/steps/<int:step_id>/status", methods=["POST"])
@login_required
def update_shot_step_status(shot_id, step_id):
    try:
        data = request.json
        new_status = data.get("status")

        if not new_status:
            return jsonify({"success": False, "message": "Status is required"}), 400

        conn = get_db()
        cursor = conn.cursor()

        # Get the corresponding node ID for the status
        node_row = cursor.execute("""
            SELECT id FROM nodes WHERE name = ? AND step_id = ?
        """, (new_status, step_id)).fetchone()

        if not node_row:
            return jsonify({"success": False, "message": f"Invalid status: {new_status}"}), 400

        new_node_id = node_row["id"]

        # Update the primary status
        cursor.execute("""
            INSERT INTO shot_step_assignments (shot_id, step_id, status)
            VALUES (?, ?, ?)
            ON CONFLICT (shot_id, step_id) DO UPDATE SET status = ?
        """, (shot_id, step_id, new_status, new_status))

        # Handle linked steps
        linked_rows = cursor.execute("""
            SELECT linked_step_id FROM links WHERE step_id = ?
        """, (step_id,)).fetchall()

        for linked_row in linked_rows:
            linked_step_id = linked_row["linked_step_id"]

            # Avoid redundant updates for already matching statuses
            existing_status = cursor.execute("""
                SELECT status FROM shot_step_assignments
                WHERE shot_id = ? AND step_id = ?
            """, (shot_id, linked_step_id)).fetchone()

            if not existing_status or existing_status["status"] != new_status:
                cursor.execute("""
                    INSERT INTO shot_step_assignments (shot_id, step_id, status)
                    VALUES (?, ?, ?)
                    ON CONFLICT (shot_id, step_id) DO UPDATE SET status = ?
                """, (shot_id, linked_step_id, new_status, new_status))

        conn.commit()
        return jsonify({"success": True, "message": "Status updated successfully"})

    except Exception as e:
        conn.rollback()
        print(f"âŒ Error updating shot step status: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/api/films/shots/bulk-update", methods=["POST"])
@login_required
def bulk_update_shot_statuses():
    from collections import deque
    conn = get_db()
    cursor = conn.cursor()

    try:
        data = request.json
        updates = data.get("updates", [])

        if not updates:
            return jsonify({"success": False, "message": "No updates provided"}), 400

        queue = deque()
        visited = set()

        # Step 1: seed queue with direct updates
        for update in updates:
            shot_id = int(update["shot_id"])
            step_id = int(update["step_id"])
            new_status = update["status"]
            queue.append((shot_id, step_id, new_status))

        # Step 2: process queue recursively
        while queue:
            shot_id, step_id, new_status = queue.popleft()
            key = (shot_id, step_id, new_status)
            if key in visited:
                continue
            visited.add(key)

            cursor.execute("""
                INSERT INTO shot_step_assignments (shot_id, step_id, status)
                VALUES (?, ?, ?)
                ON CONFLICT (shot_id, step_id) DO UPDATE SET status = ?
            """, (shot_id, step_id, new_status, new_status))

            # Get current node_id for this status
            current_node = cursor.execute("""
                SELECT node_id FROM nodes WHERE step_id = ? AND name = ?
            """, (step_id, new_status)).fetchone()

            if not current_node:
                continue  # No node match found, skip

            # Get children (crossflow links)
            links = cursor.execute("""
                SELECT to_flow_id, child_node_id FROM links
                WHERE step_id = ? AND parent_node_id = ?
                  AND to_flow_id IS NOT NULL AND child_node_id IS NOT NULL
            """, (step_id, current_node["node_id"])).fetchall()

            for link in links:
                linked_step_id = link["to_flow_id"]
                child_node_id = link["child_node_id"]

                # Get status name from child_node_id
                result = cursor.execute("""
                    SELECT name FROM nodes WHERE node_id = ?
                """, (child_node_id,)).fetchone()
                if result:
                    queue.append((shot_id, linked_step_id, result["name"]))

        conn.commit()
        return jsonify({"success": True, "message": "Bulk status update successful"})

    except Exception as e:
        conn.rollback()
        print(f"âŒ Error during bulk status update: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/scenes/<int:scene_id>/shots/add", methods=["GET", "POST"])
def add_shot_route(scene_id):
    import datetime
    from datetime import date
    db = get_db()

    success = False

    # Fetch the current scene
    scene = db.execute("SELECT * FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if not scene:
        abort(404)

    # Fetch the associated film for the scene
    film = db.execute("SELECT * FROM films WHERE id = ?", (scene["film_id"],)).fetchone()
    if not film:
        abort(404)

    # Fetch only users who are part of the film crew
    crew_users = db.execute("""
        SELECT u.id, u.name
        FROM users u
        JOIN film_crew fc ON fc.user_id = u.id
        WHERE fc.film_id = ?
        ORDER BY u.name
    """, (film["id"],)).fetchall()

    if request.method == "POST":
        shot_number = request.form.get("shot_number", "").strip()
        
        if not (1 <= len(shot_number) <= 3) or not shot_number.isdigit():
            flash("Shot number must be between 1 and 3 digits.")
            return redirect(url_for("films.add_shot_route", scene_id=scene_id))

        description = request.form.get("description", "")
        start_date = request.form.get("start_date", "")
        due_date = request.form.get("due_date", "")
        assigned_to = request.form.get("assigned_to")

        try:
            assigned_to_id = int(assigned_to) if assigned_to else None
        except ValueError:
            assigned_to_id = None

        # Parse start_date (fallback = today)
        if start_date:
            base_start = datetime.date.fromisoformat(start_date)
        else:
            base_start = datetime.date.today()

        db.execute("""
            INSERT INTO shots (scene_id, shot_number, description, start_date, due_date, assigned_to)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (scene_id, shot_number, description, base_start.isoformat(), due_date, assigned_to_id))
        db.commit()
        
        shot_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Exclude pre-production steps
        excluded_step_ids = [row["step_id"] for row in db.execute("""
            SELECT step_id FROM film_step_progress
            WHERE film_id = ?
        """, (scene["film_id"],)).fetchall()]

        # Get all steps for the workflow (excluding pre-pro)
        steps = db.execute("""
            SELECT st.id, st.name
            FROM steps st
            WHERE st.parent_id = ?
            AND st.id NOT IN ({})
            ORDER BY st.order_num ASC
        """.format(",".join("?" * len(excluded_step_ids))), [film["step_id"]] + excluded_step_ids).fetchall()

        # Chain scheduling
        current_date = base_start
        for step in steps:
            step_name = step["name"].strip()

            duration_days = 7  # default 1 week
            if step_name.startswith("FB "):
                duration_days = 7  # feedback steps always 1 week

            step_end = current_date + datetime.timedelta(days=duration_days)

            # Top node for initial status
            top_node = db.execute("""
                SELECT name FROM nodes
                WHERE step_id = ?
                ORDER BY CAST(substr(position, instr(position, ' ') + 1) AS INTEGER)
                LIMIT 1
            """, (step["id"],)).fetchone()

            status = top_node["name"] if top_node else "Not Started"

            db.execute("""
                INSERT INTO shot_step_assignments (shot_id, step_id, status, due_date)
                VALUES (?, ?, ?, ?)
            """, (
                shot_id,
                step["id"],
                status,
                step_end.isoformat()
            ))

            current_date = step_end  # advance timeline

        db.commit()
        success = True
        return redirect(url_for("films.view_shots_route", scene_id=scene_id))

    return render_template(
        "films/add_shot.html",
        scene=scene,
        users=crew_users,
        success=success,
        today=date.today().isoformat()
    )

@films_bp.route("/scenes/<int:scene_id>/shots/add-multiple", methods=["POST"])
def add_multiple_shots(scene_id):
    import datetime
    db = get_db()

    # Validate the scene exists
    scene = db.execute("SELECT * FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if not scene:
        abort(404)

    # Validate the film exists
    film = db.execute("SELECT * FROM films WHERE id = ?", (scene["film_id"],)).fetchone()
    if not film:
        abort(404)

    # Validate prefix
    prefix = request.form.get("prefix", "").strip()
    if not prefix.isdigit() or len(prefix) != 3:
        flash("Prefix must be exactly 3 digits (e.g., 010, 100).")
        return redirect(url_for("films.add_shot_route", scene_id=scene_id))

    # Get the count
    try:
        count = int(request.form.get("count", 0))
        if count <= 0:
            raise ValueError
    except ValueError:
        flash("Count must be a positive number.")
        return redirect(url_for("films.add_shot_route", scene_id=scene_id))

    description = request.form.get("description", "")
    start_date = request.form.get("start_date", "")
    due_date = request.form.get("due_date", "")
    assigned_to = request.form.get("assigned_to")

    # Convert assigned_to
    try:
        assigned_to_id = int(assigned_to) if assigned_to else None
    except ValueError:
        assigned_to_id = None

    # Convert prefix to int
    start_number = int(prefix)

    # Parse start_date (fallback = today so due_dates don't end up NULL)
    if start_date:
        base_start = datetime.date.fromisoformat(start_date)
    else:
        base_start = datetime.date.today()

    # Exclude pre-pro steps
    excluded_step_ids = [row["step_id"] for row in db.execute("""
        SELECT step_id FROM film_step_progress
        WHERE film_id = ?
    """, (film["id"],)).fetchall()]

    # Get production steps for this workflow
    steps = db.execute("""
        SELECT st.id, st.name
        FROM steps st
        WHERE st.parent_id = ?
        AND st.id NOT IN ({})
        ORDER BY st.order_num ASC
    """.format(",".join("?" * len(excluded_step_ids))), [film["step_id"]] + excluded_step_ids).fetchall()

    for i in range(count):
        shot_number = f"{start_number + i * 10:03}"

        db.execute("""
            INSERT INTO shots (scene_id, shot_number, description, start_date, due_date, assigned_to)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (scene_id, shot_number, description, start_date, due_date, assigned_to_id))

        shot_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Chain scheduling
        current_date = base_start
        for step in steps:
            step_name = step["name"].strip()

            # Default duration: 1 week
            duration_weeks = 1
            duration_days = duration_weeks * 7

            if current_date:
                step_start = current_date
                step_end = step_start + datetime.timedelta(days=duration_days)
            else:
                step_start, step_end = None, None

            # FB step → starts right after its parent’s end
            if step_name.startswith("FB ") and step_start:
                step_end = step_start + datetime.timedelta(days=7)

            # Insert node status
            top_node = db.execute("""
                SELECT name FROM nodes
                WHERE step_id = ?
                ORDER BY CAST(substr(position, instr(position, ' ') + 1) AS INTEGER)
                LIMIT 1
            """, (step["id"],)).fetchone()

            status = top_node["name"] if top_node else "Not Started"

            # 🔹 Only store due_date in DB
            db.execute("""
                INSERT INTO shot_step_assignments (shot_id, step_id, status, due_date)
                VALUES (?, ?, ?, ?)
            """, (
                shot_id,
                step["id"],
                status,
                step_end.isoformat() if step_end else None
            ))

            current_date = step_end  # advance timeline

    db.commit()
    flash(f"🎬 Added {count} shots starting at {prefix}")
    return redirect(url_for("films.view_shots_route", scene_id=scene_id))

@films_bp.route("/scenes/<int:scene_id>/shots/delete-multiple", methods=["POST"])
def delete_multiple_shots(scene_id):
    db = get_db()
    shot_ids = request.form.getlist("shot_ids")

    for shot_id in shot_ids:
        db.execute("DELETE FROM shot_step_assignments WHERE shot_id = ?", (shot_id,))
        db.execute("DELETE FROM shots WHERE id = ?", (shot_id,))

    db.commit()
    flash(f"ðŸ—‘ï¸ Deleted {len(shot_ids)} shots.")
    return redirect(url_for("films.view_shots_route", scene_id=scene_id))

@films_bp.route("/scenes/<int:scene_id>/shots", methods=["GET"])
@login_required
def view_shots_route(scene_id):
    db = get_db()

    # Fetch the current scene
    scene = db.execute("SELECT * FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    if not scene:
        print("âš ï¸ Scene not found")
        return "Scene not found", 404

    # Fetch the associated film for this scene
    film = db.execute("SELECT * FROM films WHERE id = ?", (scene["film_id"],)).fetchone()
    if not film:
        print("âš ï¸ Film not found")
        return "Film not found", 404

    # Fetch all scenes for the dropdown
    scenes = db.execute("""
        SELECT id, scene_number
        FROM scenes
        WHERE film_id = ?
        ORDER BY scene_number ASC
    """, (film["id"],)).fetchall()

    # Fetch all shots for this scene
    shots = [dict(row) for row in db.execute(
        """
        SELECT s.*, u.name as assignee
        FROM shots s
        LEFT JOIN users u ON s.assigned_to = u.id
        WHERE s.scene_id = ?
        ORDER BY s.shot_number
        """,
        (scene_id,)
    ).fetchall()]

    # Exclude pre-production steps
    pre_production_steps = [row["step_id"] for row in db.execute(
        """
        SELECT DISTINCT step_id
        FROM film_step_progress
        WHERE film_id = ?
        """,
        (film["id"],)
    ).fetchall()]

    # Fetch all steps for this film's main workflow
    steps_raw = db.execute(
        f"""
        SELECT st.id, st.name, st.parent_id
        FROM steps st
        WHERE st.parent_id = ? AND st.id NOT IN ({','.join(map(str, pre_production_steps))})
        ORDER BY st.order_num ASC
        """,
        (film["step_id"],)
    ).fetchall()

    # Build steps map
    steps_map = {step["id"]: {
        "step_id": step["id"],
        "step_name": step["name"] or "Unnamed Step",
        "status_options": []
    } for step in steps_raw}

    # Attach status options to each step
    for step_id, step_data in steps_map.items():
        nodes = db.execute(
            """
            SELECT id, name, color
            FROM nodes
            WHERE step_id = ?
            ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS FLOAT) ASC
            """,
            (step_id,)
        ).fetchall()

        for node in nodes:
            step_data["status_options"].append({
                "id": node["id"],                # [OK] this was missing
                "name": node["name"],
                "color": node["color"] or "#cccccc"
            })

    # Enrich shots with step statuses
    for shot in shots:
        shot["steps"] = []

        # Fetch current statuses for this shot
        step_assignments = db.execute(
            """
            SELECT step_id, status, assigned_to, due_date
            FROM shot_step_assignments
            WHERE shot_id = ?
            """,
            (shot["id"],)
        ).fetchall()

        step_status_map = {a["step_id"]: dict(a) for a in step_assignments}

        # Attach current status and color
        for step_id, step_data in steps_map.items():
            assignment = step_status_map.get(step_id, {})
            # Default to this step's actual first node (e.g. "Ready to Start") when no
            # shot_step_assignments row exists yet, so the dropdown always has a real,
            # matching option to select instead of silently falling back to whichever
            # node happens to sort first.
            default_status = step_data["status_options"][0]["name"] if step_data["status_options"] else "Not Started"
            current_status = assignment.get("status", default_status)
            status_color = next((opt["color"] for opt in step_data["status_options"] if opt["name"] == current_status), "#cccccc")

            # Build the step structure
            shot["steps"].append({
                "step_id": step_id,
                "step_name": step_data["step_name"],
                "status": current_status,
                "status_color": status_color,
                "status_options": step_data["status_options"],
                "assigned_to": assignment.get("assigned_to", ""),
                "due_date": assignment.get("due_date", "")
            })

    # Fetch all crew members for assignment dropdown
    crew = db.execute(
        """
        SELECT u.id, u.name, MAX(g.permission_level) as permission_level
        FROM users u
        JOIN film_crew fc ON fc.user_id = u.id
        LEFT JOIN user_groups ug ON ug.user_id = u.id
        LEFT JOIN groups g ON g.id = ug.group_id
        WHERE fc.film_id = ?
        GROUP BY u.id
        ORDER BY u.name
        """,
        (film["id"],)
    ).fetchall()

    steps = db.execute("SELECT id, name FROM steps").fetchall()
    steps = [dict(row) for row in steps]

    # Render the template
    return render_template(
        "films/view_shots.html",
        scene=scene,
        scenes=scenes,
        film=film,
        shots=shots,
        steps=list(steps_map.values()),
        crew=crew,
        visible_step_ids=set(map(int, request.args.getlist("visible_steps"))),
        active_page="scenes"
    )

@films_bp.route("/shots/edit", methods=["POST"])
def edit_shot_route():
    db = get_db()
    shot_id = int(request.form.get("shot_id"))

    description = request.form.get("description")
    start_date = request.form.get("start_date")
    due_date = request.form.get("due_date")

    try:
        db.execute("""
            UPDATE shots
            SET description = ?, start_date = ?, due_date = ?
            WHERE id = ?
        """, (description, start_date, due_date, shot_id))
        db.commit()

        # If AJAX, return JSON
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True})

        flash("[ERROR]ï¸ Shot updated.")
        return redirect(request.referrer or url_for("films.view_films"))

    except Exception as e:
        db.rollback()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": str(e)}), 500
        flash(f"âŒ Error updating shot: {e}")
        return redirect(request.referrer or url_for("films.view_films"))

@films_bp.route('/films/bulk_edit_shots', methods=['POST'])
def bulk_edit_shots():
    try:
        data = request.json
        shot_ids = data.get('shot_ids', [])
        updates = data.get('updates', {})
        step_updates = data.get('step_updates', {})

        # Use the shared database connection
        db = get_db()
        cursor = db.cursor()

        # Update main shot fields
        if updates:
            for shot_id in shot_ids:
                set_clauses = []
                params = []
                if 'description' in updates:
                    set_clauses.append("description = ?")
                    params.append(updates['description'])
                if 'start_date' in updates:
                    set_clauses.append("start_date = ?")
                    params.append(updates['start_date'])
                if 'due_date' in updates:
                    set_clauses.append("due_date = ?")
                    params.append(updates['due_date'])
                if 'assigned_to' in updates:
                    set_clauses.append("assigned_to = ?")
                    params.append(updates['assigned_to'])

                # Only run the update if there are fields to update
                if set_clauses:
                    sql = f"UPDATE shots SET {', '.join(set_clauses)} WHERE id = ?"
                    params.append(shot_id)
                    cursor.execute(sql, params)

        # Update step-specific fields
        for key, value in step_updates.items():
            prefix, step_id = key.rsplit('_', 1)
            step_id = int(step_id)
            field = 'status' if prefix == 'step_status' else 'assigned_to' if prefix == 'step_assigned' else 'due_date'

            for shot_id in shot_ids:
                cursor.execute(
                    f"UPDATE shot_step_assignments SET {field} = ? WHERE shot_id = ? AND step_id = ?",
                    (value, shot_id, step_id)
                )

        # Commit the changes
        db.commit()

        return jsonify(success=True, message="Shots updated successfully.")
    except Exception as e:
        print(f"Error in bulk_edit_shots: {e}")
        return jsonify(success=False, message="Failed to update shots."), 500

@films_bp.route("shots/update-shot-status", methods=["POST"])
def update_shot_status():
    db = get_db()
    data = request.json

    shot_id = data.get("shot_id")
    step_id = data.get("step_id")
    new_status = data.get("status")

    if not shot_id or not step_id or not new_status:
        return jsonify({"success": False, "error": "Missing shot_id, step_id, or status"}), 400

    # Fetch the corresponding node ID and color
    node = db.execute("""
        SELECT id AS node_id, color 
        FROM nodes
        WHERE step_id = ? AND name = ?
    """, (step_id, new_status)).fetchone()


    if not node:
        return jsonify({"success": False, "error": "Node not found for this step and status"}), 404

    node_id = node["node_id"]
    node_color = node["color"] or "#ffffff"

    # Update the node in shot_step_assignments
    db.execute("""
        UPDATE shot_step_assignments
        SET status = ?
        WHERE shot_id = ? AND step_id = ?
    """, (new_status, shot_id, step_id))

    # FB Animation/FB Blocking reaching Approved locks the sibling
    # production step (step_locks, entity_type='shot_step'). Note this only
    # fires when the FB variant specifically is marked Approved -- marking
    # the production step ("Blocking") itself Approved does NOT set this
    # lock, which is exactly the trap that made an earlier manual approval
    # look like it worked (both showed "Approved") without actually
    # unlocking anything downstream. The real per-shot gates
    # (shot_layout_approved/shot_blocking_approved/shot_animation_approved
    # in capstone_routes.py and get_dashboard_data() below) read
    # shot_step_assignments.status directly instead, so they don't depend
    # on this FB/production distinction or on step_locks at all -- this
    # block is left as harmless bookkeeping, not the source of truth.
    # FB Lighting isn't included -- Lighting is the last file-versioned
    # step, there's nothing after it to unlock (Comp is out of scope).
    SHOT_FB_UNLOCKS_STEP = {"FB Animation": "Animation", "FB Blocking": "Blocking"}
    if new_status == "Approved":
        fb_step_row = db.execute("SELECT name, parent_id FROM steps WHERE id = ?", (step_id,)).fetchone()
        production_step_name = SHOT_FB_UNLOCKS_STEP.get(fb_step_row["name"]) if fb_step_row else None

        if production_step_name:
            production_step = db.execute(
                "SELECT id FROM steps WHERE parent_id = ? AND name = ?",
                (fb_step_row["parent_id"], production_step_name)
            ).fetchone()

            if production_step:
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                approver_id = session.get("user_id")
                db.execute("""
                    INSERT INTO step_locks (entity_type, entity_id, step_id, locked, locked_by, locked_at)
                    VALUES ('shot_step', ?, ?, 1, ?, ?)
                    ON CONFLICT(entity_type, entity_id, step_id)
                    DO UPDATE SET locked = 1, locked_by = excluded.locked_by, locked_at = excluded.locked_at
                """, (shot_id, production_step["id"], approver_id, now))

    db.commit()

    return jsonify({
        "success": True,
        "message": "[OK] Shot status updated.",
        "status_color": node_color
    })

@films_bp.route("/api/shot-crossflow-updates", methods=["POST"])
def api_shot_crossflow_updates():
    from collections import deque
    import traceback
    db = get_db()

    try:
        data = request.get_json()
        shot_id = int(data.get("shot_id"))
        origin_step_id = int(data.get("step_id"))
        origin_node_id = int(data.get("node_id"))

        if not all([shot_id, origin_step_id, origin_node_id]):
            return jsonify({"error": "Missing required fields"}), 400

        updated = []
        seen = set()
        queue = deque()
        queue.append((origin_step_id, origin_node_id))

        while queue:
            step_id, node_id = queue.popleft()
            key = (step_id, node_id)

            if key in seen:
                continue
            seen.add(key)

            # Find all outgoing links from this node
            links = db.execute("""
                SELECT to_flow_id, child_node_id
                FROM links
                WHERE step_id = ? AND parent_node_id = ? AND to_flow_id IS NOT NULL
            """, (step_id, node_id)).fetchall()

            for link in links:
                to_flow_id = link["to_flow_id"]
                child_node_id = link["child_node_id"]

                # Get the target status name + color
                target_node = db.execute("""
                    SELECT name, color FROM nodes WHERE id = ?
                """, (child_node_id,)).fetchone()

                if not target_node:
                    print(f"âš ï¸ Skipping missing child_node_id: {child_node_id}")
                    continue

                new_status = target_node["name"]
                color = target_node["color"] or "#ffffff"

                # Insert or update shot_step_assignments
                exists = db.execute("""
                    SELECT 1 FROM shot_step_assignments
                    WHERE shot_id = ? AND step_id = ?
                """, (shot_id, to_flow_id)).fetchone()

                if exists:
                    db.execute("""
                        UPDATE shot_step_assignments
                        SET status = ?
                        WHERE shot_id = ? AND step_id = ?
                    """, (new_status, shot_id, to_flow_id))
                else:
                    db.execute("""
                        INSERT INTO shot_step_assignments (shot_id, step_id, status)
                        VALUES (?, ?, ?)
                    """, (shot_id, to_flow_id, new_status))

                updated.append({
                    "step_id": to_flow_id,
                    "new_status": new_status,
                    "color": color
                })

                # Queue next wave
                queue.append((to_flow_id, child_node_id))

        db.commit()
        return jsonify(updated)

    except Exception as e:
        db.rollback()
        print("âŒ Crossflow error:", traceback.format_exc())
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@films_bp.route("/shots/update-due-date", methods=["POST"])
def update_due_date():
    db = get_db()
    data = request.get_json()

    shot_id = data.get("shot_id")
    step_id = data.get("step_id")
    due_date = data.get("due_date")

    if not shot_id or not step_id:
        return jsonify({"error": "Missing data"}), 400

    existing = db.execute("""
        SELECT 1 FROM shot_step_assignments
        WHERE shot_id = ? AND step_id = ?
    """, (shot_id, step_id)).fetchone()

    if existing:
        db.execute("""
            UPDATE shot_step_assignments
            SET due_date = ?
            WHERE shot_id = ? AND step_id = ?
        """, (due_date, shot_id, step_id))
    else:
        db.execute("""
            INSERT INTO shot_step_assignments (shot_id, step_id, due_date, status)
            VALUES (?, ?, ?, ?)
        """, (shot_id, step_id, due_date, "Not Started"))

    db.commit()
    return jsonify({"success": True})

@films_bp.route("/shots/<int:shot_id>/delete", methods=["POST"])
def delete_shot_route(shot_id):
    db = get_db()

    # First delete any shot_step_assignments
    db.execute("DELETE FROM shot_step_assignments WHERE shot_id = ?", (shot_id,))

    # Then delete the actual shot
    db.execute("DELETE FROM shots WHERE id = ?", (shot_id,))

    db.commit()

    flash("ðŸ—‘ï¸ Shot deleted successfully.")
    return redirect(request.referrer or url_for("films.view_shots_route", scene_id=1))

@films_bp.route("/update-assigned-user", methods=["POST"])
def update_assigned_user():
    db = get_db()
    data = request.get_json()

    shot_id = data.get("shot_id")
    step_id = data.get("step_id")
    user_id = data.get("user_id")

    if not shot_id or not step_id:
        return jsonify({"error": "Missing data"}), 400

    existing = db.execute("""
        SELECT 1 FROM shot_step_assignments
        WHERE shot_id = ? AND step_id = ?
    """, (shot_id, step_id)).fetchone()

    if existing:
        db.execute("""
            UPDATE shot_step_assignments
            SET assigned_to = ?
            WHERE shot_id = ? AND step_id = ?
        """, (user_id, shot_id, step_id))
    else:
        db.execute("""
            INSERT INTO shot_step_assignments (shot_id, step_id, assigned_to, status)
            VALUES (?, ?, ?, ?)
        """, (shot_id, step_id, user_id, "Not Started"))

    db.commit()
    return jsonify({"success": True})

# ----------------------------------------------------------------------------------------------------------------------
# CREW MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

@films_bp.route("/<int:film_id>/crew", methods=["GET"])
def view_crew_for_film(film_id):
    print("[OK] Received Form Data:", request.form)

    db = get_db()

    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        abort(404)

    coordinator_roles = db.execute("""
        SELECT * FROM groups
        WHERE section = 'films' AND name LIKE '%Coordinator%'
        ORDER BY name
    """).fetchall()

    artists = db.execute("""
        SELECT u.id, u.name
        FROM users u
        JOIN user_groups ug ON u.id = ug.user_id
        WHERE ug.group_id = 11
        ORDER BY u.name
    """).fetchall()

    current_crew = db.execute("""
        SELECT fc.user_id, fc.group_id, u.name as user_name, g.name as role_name
        FROM film_crew fc
        JOIN users u ON fc.user_id = u.id
        JOIN groups g ON fc.group_id = g.id
        WHERE fc.film_id = ?
    """, (film_id,)).fetchall()

    # ðŸš€ Add this print to confirm the film ID
    print("[OK] Loaded film:", film)

    return render_template(
        "partials/crew_modal.html",
        film=film,
        coordinator_roles=coordinator_roles,
        artists=artists,
        current_crew=current_crew
    )

@films_bp.route("/<int:film_id>/crew", methods=["POST"])
def update_crew_for_film(film_id):
    print("[OK] Received Form Data:", request.form)
    db = get_db()

    # [OK] Remove all existing crew for this film
    db.execute("DELETE FROM film_crew WHERE film_id = ?", (film_id,))

    inserted_set = set()

    for key, values in request.form.lists():
        match = re.match(r"crew\[(\d+)\]", key)
        if not match:
            continue

        group_id = int(match.group(1))

        # Handle multiple artists (group 11) or single selects
        user_ids = values if isinstance(values, list) else [values]

        for user_id in user_ids:
            try:
                crew_member = (int(user_id), group_id)
                if crew_member not in inserted_set:
                    db.execute(
                        "INSERT INTO film_crew (film_id, user_id, group_id) VALUES (?, ?, ?)",
                        (film_id, int(user_id), group_id)
                    )
                    inserted_set.add(crew_member)
            except Exception as e:
                print(f"âŒ Insert failed for user {user_id}: {e}")

    db.commit()

    return jsonify({"success": True, "message": "Crew updated successfully."})

# ----------------------------------------------------------------------------------------------------------------------
# ASSET MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

@films_bp.route("/films/<int:film_id>/assets", methods=["GET"], endpoint="view_assets")
def view_assets(film_id):
    db = get_db()

    try:
        # Fetch the film object
        film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
        if not film:
            return "Film not found", 404

        # Fetch all assets for this film
        assets = db.execute("""
            SELECT id, name, category, due_date
            FROM assets
            WHERE film_id = ?
            ORDER BY name
        """, (film_id,)).fetchall()

        if not assets:
            assets = []  # Just proceed with an empty list


        # Group assets by category and calculate progress
        categories = {
            "Sets": [],
            "BGs": [],
            "Character/Rigs": [],
            "Props - 3D": [],
            "Props - 2D": []
        }

        asset_progress = {}

        film_name = film["name"]
        mutable_assets = []
        print("starting asset loop")
        for asset in assets:
            asset_dict = dict(asset)
            asset_dict["file_path"] = find_matching_asset_file(film_name, asset["category"], asset["name"])

            print("Asset check:", asset["name"], asset["category"], asset_dict["file_path"])
            mutable_assets.append(asset_dict)

        # Proceed with progress + category grouping using `mutable_assets`
        for asset in mutable_assets:
            asset_id = asset["id"]

            # Calculate progress
            total_steps = db.execute("""
                SELECT COUNT(*)
                FROM asset_step_assignments
                WHERE asset_id = ?
            """, (asset_id,)).fetchone()[0]

            completed_steps = db.execute("""
                SELECT COUNT(*)
                FROM asset_step_assignments asa
                JOIN nodes n ON asa.node_id = n.id
                WHERE asa.asset_id = ? AND n.completion_percentage = 100
            """, (asset_id,)).fetchone()[0]

            progress = (completed_steps / total_steps) * 100 if total_steps > 0 else 0
            asset_progress[asset_id] = round(progress)

            # Add to category
            category = asset["category"] or "Uncategorized"
            if category not in categories:
                categories[category] = []
            categories[category].append(asset)


        # Render the template
        return render_template(
            "films/view_assets.html",
            categories=categories,
            asset_progress=asset_progress,
            film=dict(film),
            all_films=get_all_films(),
            active_page="assets"
        )

    except Exception as e:
        print(f"Error fetching assets for film {film_id}: {e}")
        return "Error loading assets", 500

def _sync_assets_from_disk(db, film_id):
    """
    Core "Sync from Disk" logic -- shared by the sync_asset_disk() button
    route and add_asset(), so a newly created asset gets its file_path
    resolved the same way a manual sync would, without needing a separate
    click. Returns the number of assets updated. Caller is responsible for
    db.commit().
    """
    film = db.execute("SELECT name FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return None

    film_name = film["name"]

    assets = db.execute("""
        SELECT id, name, category, file_path
        FROM assets
        WHERE film_id = ?
    """, (film_id,)).fetchall()

    updated = 0
    for asset in assets:
        resolved_path = find_matching_asset_file(
            film_name,
            asset["category"],
            asset["name"]
        )

        # Only update if changed
        if resolved_path and resolved_path != asset["file_path"]:
            db.execute("""
                UPDATE assets
                SET file_path = ?
                WHERE id = ?
            """, (resolved_path, asset["id"]))
            updated += 1

    return updated


@films_bp.route("/films/assets/sync-disk/<int:film_id>", methods=["POST"])
def sync_asset_disk(film_id):
    db = get_db()

    updated = _sync_assets_from_disk(db, film_id)
    if updated is None:
        return jsonify({"error": "Film not found"}), 404

    db.commit()

    return jsonify({
        "message": f"Sync complete. {updated} assets updated."
    })

@films_bp.route("/films/<int:film_id>/api/assets", methods=["GET"], endpoint="get_assets_for_film")
def get_assets_for_film(film_id):
    db = get_db()
    try:
        # Fetch all assets for this film
        assets = db.execute("""
            SELECT id, name, category, due_date
            FROM assets
            WHERE film_id = ?
            ORDER BY name
        """, (film_id,)).fetchall()

        # Return the assets as a JSON list
        return jsonify([dict(asset) for asset in assets])


    except Exception as e:
        print(f"âŒ Error fetching assets for film {film_id}: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/films/assets/<int:asset_id>", methods=["GET"], endpoint="view_individual_asset")
def view_individual_asset(asset_id):
    db = get_db()

    try:
        # Fetch asset details
        asset = db.execute("""
            SELECT a.id, a.name, a.category, a.due_date, s.name AS step_name
            FROM assets a
            JOIN steps s ON a.step_id = s.id
            WHERE a.id = ?
        """, (asset_id,)).fetchone()

        if not asset:
            return "Asset not found", 404

        # Fetch all step assignments for this asset
        steps = db.execute("""
            SELECT 
            asa.id AS assignment_id,
            s.id AS step_id,
            s.name AS step_name,
            asa.node_id,
            asa.status,
            asa.assigned_to,
            asa.due_date
            FROM asset_step_assignments asa
            JOIN steps s ON asa.step_id = s.id
            WHERE asa.asset_id = ?
            ORDER BY s.order_num
        """, (asset_id,)).fetchall()

        # Fetch possible statuses (nodes) for each step
        step_data = {}
        for step in steps:
            nodes = db.execute("""
                SELECT id, name, color
                FROM nodes
                WHERE step_id = ?
                ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INTEGER) ASC
            """, (step["step_id"],)).fetchall()

            step_data[step["step_id"]] = {
                "assignment_id": step["assignment_id"],
                "step_name": step["step_name"],
                "current_node_id": step["node_id"],
                "current_status": step["status"],
                "nodes": nodes
            }

        # Fetch film crew for assignee dropdown
        crew_members = db.execute("""
            SELECT fc.user_id, u.name
            FROM film_crew fc
            JOIN users u ON fc.user_id = u.id
            WHERE fc.film_id = ?
        """, (asset["id"],)).fetchall()

        return render_template(
            "films/individual_assets_view.html",
            asset=asset,
            assignments=list(steps),       # [OK] This is what the template expects
            step_nodes=[node for step in step_data.values() for node in step["nodes"]],
            crew=crew_members,
            all_categories=[],             # Include if you have dropdowns
            all_films=get_all_films(),     # For film selector
            film={"id": asset_id, "name": asset["name"]},  # Dummy fallback film
        )


    except Exception as e:
        print(f"âŒ Error loading asset {asset_id}: {e}")
        return "Error loading asset", 500

@films_bp.route("/films/<int:film_id>/assets/add", methods=["GET", "POST"], endpoint="add_asset")
def add_asset(film_id):
    db = get_db()
    import datetime, json, os
    try:
        # 🔹 Load default timelines JSON
        json_path = os.path.join(current_app.root_path, "utils", "default_timelines.json")
        with open(json_path, "r") as f:
            default_timeline = json.load(f)

        if request.method == "POST":
            name = request.form.get("name")
            category = request.form.get("category")
            due_date = request.form.get("due_date", None)

            if not name or not category:
                return jsonify({"success": False, "message": "Name and category are required"}), 400

            # 🔹 Find anchor: Locked Script end date
            locked_script = db.execute("""
                SELECT end_date
                FROM preproduction_steps
                WHERE film_id = ? AND step_name = 'Locked_Script'
                ORDER BY end_date DESC
                LIMIT 1
            """, (film_id,)).fetchone()

            anchor_date = datetime.date.today()
            if locked_script and locked_script["end_date"]:
                try:
                    anchor_date = datetime.date.fromisoformat(locked_script["end_date"])
                except Exception:
                    pass  # fallback to today if parsing fails

            # If no due_date provided, calculate based on total weeks
            if not due_date:
                total_weeks = sum(step.get("weeks", 0) for step in default_timeline["Assets"].get(category, []))
                due_date = anchor_date + datetime.timedelta(weeks=total_weeks)
                due_date = due_date.strftime("%Y-%m-%d")

            # Step 1: Get parent step (e.g., "Sets", "BGs", etc.)
            parent_step = db.execute("""
                SELECT id FROM steps WHERE name = ? AND parent_id IS NULL
            """, (category,)).fetchone()

            if not parent_step:
                return jsonify({"success": False, "message": f"No parent step found for category '{category}'"}), 404

            parent_step_id = parent_step["id"]

            # Step 2: Insert new asset (with top-level due_date)
            cursor = db.execute("""
                INSERT INTO assets (name, category, step_id, film_id, due_date)
                VALUES (?, ?, ?, ?, ?)
            """, (name, category, parent_step_id, film_id, due_date))
            asset_id = cursor.lastrowid

            # 🔥 Auto-resolve and store file_path immediately
            film_row = db.execute(
                "SELECT name FROM films WHERE id = ?",
                (film_id,)
            ).fetchone()

            film_name = film_row["name"] if film_row else None

            # Create Assets/<Category>/<Asset Name>/ on disk right away --
            # previously only "Generate Folders" (driven by a manually
            # re-exported film_config_v1.json) ever created asset folders,
            # so an asset added here had nowhere to save a file into until
            # someone re-ran that whole export/generate cycle.
            if film_name:
                try:
                    ensure_asset_folder(film_name, category, name)
                except OSError as e:
                    print(f"⚠️ Could not create asset folder for '{name}' ({category}): {e}")

            # Sync from Disk for the whole film, not just this new asset --
            # same helper the "Sync Disk" button calls, so adding an asset
            # does exactly what that button does automatically (this new
            # asset's folder was just created and is empty, so it'll
            # resolve to nothing yet, but every other asset in the film
            # gets re-checked too).
            _sync_assets_from_disk(db, film_id)

            # Step 3: Load default schedule for this category
            step_defs = default_timeline["Assets"].get(category, [])
            current_due = anchor_date  # 🔹 anchor to Locked Script

            # Step 4: For each defined step in JSON, create assignment with due_date
            for step_def in step_defs:
                step_name = step_def["name"]
                weeks = step_def.get("weeks", 0)
                current_due += datetime.timedelta(weeks=weeks)

                # Find matching step in DB
                step_row = db.execute("""
                    SELECT id FROM steps
                    WHERE name = ? AND parent_id = ?
                """, (step_name, parent_step_id)).fetchone()

                if not step_row:
                    continue

                step_id = step_row["id"]

                # Find first node for this step
                first_node = db.execute("""
                    SELECT id, name
                    FROM nodes
                    WHERE step_id = ?
                    ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INTEGER) ASC
                    LIMIT 1
                """, (step_id,)).fetchone()

                if first_node:
                    db.execute("""
                        INSERT INTO asset_step_assignments (asset_id, step_id, node_id, status, due_date)
                        VALUES (?, ?, ?, ?, ?)
                    """, (asset_id, step_id, first_node["id"], first_node["name"], current_due.isoformat()))

            db.commit()
            return redirect(url_for("films.view_assets", film_id=film_id))

        return render_template("films/add_asset.html", film_id=film_id, default_weeks=6)

    except Exception as e:
        print(f"Error adding asset for film {film_id}: {e}")
        db.rollback()
        return "Error adding asset", 500

@films_bp.route("/films/assets/edit", methods=["POST"], endpoint="edit_asset")
def edit_asset():
    db = get_db()
    asset_id = request.form.get("asset_id")
    name = request.form.get("name")
    due_date = request.form.get("due_date") or None

    if not asset_id or not name:
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    try:
        db.execute("""
            UPDATE assets
            SET name = ?, due_date = ?
            WHERE id = ?
        """, (name, due_date, asset_id))
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/films/assets/<int:asset_id>/edit", methods=["GET", "POST"], endpoint="edit_asset_route")
def edit_asset_route(asset_id):
    db = get_db()

    try:
        if request.method == "POST":
            name = request.form["name"]
            category = request.form["category"]
            due_date = request.form.get("due_date", None)

            # Update the asset in the database
            db.execute("""
                UPDATE assets
                SET name = ?, category = ?, due_date = ?
                WHERE id = ?
            """, (name, category, due_date, asset_id))
            db.commit()

            return redirect(url_for("films.view_individual_assets", asset_id=asset_id))

        # Fetch the asset to edit
        asset = db.execute("""
            SELECT id, name, category, due_date, film_id
            FROM assets
            WHERE id = ?
        """, (asset_id,)).fetchone()

        if not asset:
            return "Asset not found", 404

        categories = ["Sets", "BGs", "Character/Rigs", "Props - 3D", "Props - 2D"]

        return render_template("films/edit_asset.html", asset=asset, categories=categories)

    except Exception as e:
        print(f"âŒ Error editing asset {asset_id}: {e}")
        return "Error loading asset", 500

@films_bp.route("/films/assets/<int:asset_id>/delete", methods=["POST"], endpoint="delete_asset_route")
def delete_asset_route(asset_id):
    db = get_db()
    try:
        # Delete related step assignments first
        db.execute("DELETE FROM asset_step_assignments WHERE asset_id = ?", (asset_id,))

        # Now delete the asset itself
        db.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        db.commit()

        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/api/asset_status_summary/<int:asset_id>/<int:step_id>", methods=["GET"])
def asset_status_summary(asset_id, step_id):
    db = get_db()
    results = db.execute("""
        SELECT ssa.status AS status, n.color, COUNT(*) as count
        FROM asset_step_assignments ssa
        LEFT JOIN nodes n ON n.name = ssa.status AND n.step_id = ssa.step_id
        WHERE ssa.asset_id = ? AND ssa.step_id = ?
        GROUP BY ssa.status, n.color
        ORDER BY count DESC
    """, (asset_id, step_id)).fetchall()

    return jsonify([
        {
            "label": row["status"],
            "value": row["count"],
            "color": row["color"] or "#cccccc"
        } for row in results
    ])

# FB step -> the production step it unlocks. Mirrors
# dashboard_routes.py's ASSET_FB_UNLOCKS_STEP -- duplicated rather than
# cross-imported between route blueprints (consistent with the rest of
# this codebase's per-blueprint split), since this is the actual route
# the film Assets page hits, and dashboard_routes.py's copy only covers
# the personal To-Do Assets widget. FB Rigging is deliberately excluded
# here too -- Rigging is the last file-versioned step, and Shot Ready is
# already a separate coordinator action elsewhere.
ASSET_FB_UNLOCKS_STEP = {
    "FB Modeling": "Modeling",
    "FB Texture/Surface": "Texture/Surface",
}


@films_bp.route("/assets/<int:asset_id>/steps/<int:step_id>/update", methods=["POST"])
def update_asset_step(asset_id, step_id):
    db = get_db()
    data = request.get_json()
    status_name = data.get("status") or data.get("status_name")
    node_id = data.get("node_id")  # may be sent directly from JS

    try:
        # STEP 1: Resolve node_id and status if not provided
        if not node_id:
            result = db.execute("""
                SELECT id, name FROM nodes
                WHERE name = ? AND step_id = ?
            """, (status_name, step_id)).fetchone()

            if not result:
                return jsonify({"success": False, "message": f"Status '{status_name}' not found in step {step_id}"}), 404

            node_id = result["id"]
            status_name = result["name"]
        else:
            result = db.execute("""
                SELECT name FROM nodes WHERE id = ?
            """, (node_id,)).fetchone()
            status_name = result["name"] if result else None

        # STEP 2: Update current step assignment with status
        db.execute("""
            UPDATE asset_step_assignments
            SET node_id = ?, status = ?, updated_at = datetime('now')
            WHERE asset_id = ? AND step_id = ?
        """, (node_id, status_name, asset_id, step_id))

        # STEP 2b: FB Modeling/FB Texture-Surface reaching Approved unlocks
        # the next production step (step_locks, entity_type='asset_step') --
        # the same table Assets.py's resolve_current_step() and the
        # dashboard's is_active_step gating both read. See
        # ASSET_FB_UNLOCKS_STEP above for why FB Rigging isn't included.
        if status_name == "Approved":
            fb_step_row = db.execute("SELECT name FROM steps WHERE id = ?", (step_id,)).fetchone()
            production_step_name = ASSET_FB_UNLOCKS_STEP.get(fb_step_row["name"]) if fb_step_row else None

            if production_step_name:
                production_step = db.execute("""
                    SELECT s.id
                    FROM asset_step_assignments asa
                    JOIN steps s ON s.id = asa.step_id
                    WHERE asa.asset_id = ? AND s.name = ?
                """, (asset_id, production_step_name)).fetchone()

                if production_step:
                    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    approver_id = session.get("user_id")
                    db.execute("""
                        INSERT INTO step_locks (entity_type, entity_id, step_id, locked, locked_by, locked_at)
                        VALUES ('asset_step', ?, ?, 1, ?, ?)
                        ON CONFLICT(entity_type, entity_id, step_id)
                        DO UPDATE SET locked = 1, locked_by = excluded.locked_by, locked_at = excluded.locked_at
                    """, (asset_id, production_step["id"], approver_id, now))

        # STEP 3: Apply recursive crossflow updates
        visited = set()
        queue = [(node_id, step_id)]
        updated_steps = []

        while queue:
            current_node_id, current_step_id = queue.pop(0)

            if (current_node_id, current_step_id) in visited:
                continue
            visited.add((current_node_id, current_step_id))

            links = db.execute("""
                SELECT to_flow_id, child_node_id
                FROM links
                WHERE parent_node_id = ? AND step_id = ? AND to_flow_id IS NOT NULL
            """, (current_node_id, current_step_id)).fetchall()

            for link in links:
                to_step = link["to_flow_id"]
                child_node_id = link["child_node_id"]

                child_status = db.execute("SELECT name, color FROM nodes WHERE id = ?", (child_node_id,)).fetchone()
                child_status_name = child_status["name"] if child_status else None
                child_color = child_status["color"] if child_status else "#ffffff"

                existing = db.execute("""
                    SELECT 1 FROM asset_step_assignments
                    WHERE asset_id = ? AND step_id = ?
                """, (asset_id, to_step)).fetchone()

                if existing:
                    db.execute("""
                        UPDATE asset_step_assignments
                        SET node_id = ?, status = ?, updated_at = datetime('now')
                        WHERE asset_id = ? AND step_id = ?
                    """, (child_node_id, child_status_name, asset_id, to_step))
                else:
                    db.execute("""
                        INSERT INTO asset_step_assignments (asset_id, step_id, node_id, status, updated_at)
                        VALUES (?, ?, ?, ?, datetime('now'))
                    """, (asset_id, to_step, child_node_id, child_status_name))

                updated_steps.append({
                    "step_id": to_step,
                    "node_id": child_node_id,
                    "status": child_status_name,
                    "color": child_color or "#ffffff"
                })

                queue.append((child_node_id, to_step))

        db.commit()

        node_color_row = db.execute("SELECT color FROM nodes WHERE id = ?", (node_id,)).fetchone()
        node_color = (node_color_row["color"] if node_color_row else None) or "#ffffff"

        return jsonify({
            "success": True,
            "node_id": node_id,
            "color": node_color,
            "updated_steps": updated_steps
        })

    except Exception as e:
        db.rollback()
        print(f"âŒ Crossflow error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/api/asset-crossflow-updates", methods=["POST"])
def asset_crossflow_updates():
    data = request.get_json()
    asset_id = data.get("shot_id")
    step_id = data.get("step_id")
    status = data.get("status")

    print(f"ðŸ” Crossflow update triggered for asset {asset_id}, step {step_id}, status: {status}")

    return jsonify({"success": True, "message": "Crossflow hook received."})

@films_bp.route("/assets/steps/<int:assignment_id>/update_due_date", methods=["POST"])
def update_due_date_for_assignment(assignment_id):
    db = get_db()
    data = request.get_json()
    due_date = data.get("due_date")

    if due_date is None:
        return jsonify({"success": False, "message": "Missing due_date"}), 400

    try:
        db.execute("""
            UPDATE asset_step_assignments
            SET due_date = ?
            WHERE id = ?
        """, (due_date, assignment_id))
        db.commit()
        return jsonify({"success": True, "message": "Due date updated [OK]"})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/films/<int:film_id>/api/asset_categories", methods=["GET"])
def get_asset_category_progress(film_id):
    db = get_db()

    try:
        # Step 1: Get all distinct categories for this film
        categories = db.execute("""
            SELECT category, MIN(id) as asset_id
            FROM assets
            WHERE film_id = ?
            GROUP BY category
        """, (film_id,)).fetchall()

        result = []

        for cat_row in categories:
            category = cat_row["category"]
            asset_id = cat_row["asset_id"]

            # Step 2: Get step-wise status breakdown
            step_stats = db.execute("""
                WITH latest_assignments AS (
                SELECT *
                FROM asset_step_assignments
                WHERE id IN (
                    SELECT MAX(id)
                    FROM asset_step_assignments
                    GROUP BY asset_id, step_id
                )
                )
                SELECT
                    s.id AS step_id,
                    s.name AS step_name,
                    la.status,
                    COUNT(*) AS count
                FROM assets a
                JOIN latest_assignments la ON a.id = la.asset_id
                JOIN steps s ON s.id = la.step_id
                WHERE a.film_id = ? AND a.category = ?
                GROUP BY s.id, la.status
                ORDER BY s.order_num

            """, (film_id, category)).fetchall()



            # Step 3: Gather all step_ids
            step_ids = list(set([row["step_id"] for row in step_stats]))

            # Step 4: Get nodes (with color) for these steps
            if step_ids:
                nodes = db.execute(f"""
                    SELECT id, name, step_id, color
                    FROM nodes
                    WHERE step_id IN ({','.join(['?'] * len(step_ids))})
                """, step_ids).fetchall()
            else:
                nodes = []

            # Step 5: Group data by step
            step_dict = {}
            for row in step_stats:
                sid = row["step_id"]
                if sid not in step_dict:
                    step_dict[sid] = {
                        "step_name": row["step_name"],
                        "statuses": {},
                        "nodes": []
                    }
                step_dict[sid]["statuses"][row["status"]] = row["count"]

            # Step 6: Assign nodes to each step
            for node in nodes:
                sid = node["step_id"]
                if sid in step_dict:
                    step_dict[sid]["nodes"].append(dict(node))

            # Step 7: Add this category to result
            result.append({
                "category": category,
                "asset_id": asset_id,
                "steps": list(step_dict.values())
            })

        return jsonify(result)

    except Exception as e:
        print(f"Error generating asset category progress for film {film_id}: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@films_bp.route("/films/assets/category/<path:category>", methods=["GET"])
def view_asset_category(category):
    db = get_db()
    film_id = request.args.get("film_id")

    if not film_id:
        return "Film ID required", 400

    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    all_films = db.execute("SELECT id, name FROM films ORDER BY name").fetchall()

    all_categories = [
        row["category"].strip()
        for row in db.execute(
            "SELECT DISTINCT category FROM assets WHERE film_id = ? ORDER BY category", (film_id,)
        )
    ]

    assets = db.execute("""
        SELECT id, name, category
        FROM assets
        WHERE film_id = ? AND LOWER(TRIM(category)) = LOWER(TRIM(?))
        ORDER BY name
    """, (film_id, category)).fetchall()

    film_name = film["name"]
    asset_dicts = []
    for asset in assets:
        a = dict(asset)
        a["file_path"] = find_matching_asset_file(film_name, category, a["name"])
        asset_dicts.append(a)

    if not assets:
        assets = []  # Just proceed with an empty list


    asset_ids = [a["id"] for a in asset_dicts]

    assignments = db.execute(f"""
        SELECT asa.id AS assignment_id,
            asa.asset_id,
            asa.step_id,
            asa.node_id,
            asa.status,
            asa.assigned_user,
            asa.due_date,
            s.name AS step_name,
            s.order_num AS step_order
        FROM asset_step_assignments asa
        JOIN steps s ON asa.step_id = s.id
        WHERE asa.asset_id IN ({','.join(['?'] * len(asset_ids))})
        ORDER BY s.order_num
    """, asset_ids).fetchall()

    if not assignments:
        crew = db.execute("""
            SELECT fc.user_id, u.name
            FROM film_crew fc
            JOIN users u ON u.id = fc.user_id
            WHERE fc.film_id = ?
        """, (film_id,)).fetchall()

        return render_template(
            "films/individual_assets_view.html",
            film=film,
            category=category,
            assets=asset_dicts,
            assignments=[],
            step_nodes=[],
            crew=crew,
            all_categories=all_categories,
            all_films=all_films,
            message="There are assets in this category, but there are no steps assigned yet."
        )

    step_ids = list({a["step_id"] for a in assignments})
    nodes = db.execute(f"""
        SELECT id, name, step_id, color, position
        FROM nodes
        WHERE step_id IN ({','.join(['?'] * len(step_ids))})
        ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INTEGER)
    """, step_ids).fetchall()

    crew = db.execute("""
        SELECT fc.user_id, u.name
        FROM film_crew fc
        JOIN users u ON u.id = fc.user_id
        WHERE fc.film_id = ?
    """, (film_id,)).fetchall()

    return render_template(
        "films/individual_assets_view.html",
        film=film,
        category=category,
        assets=asset_dicts,
        assignments=assignments,
        step_nodes=nodes,
        crew=crew,
        all_categories=all_categories,
        all_films=all_films
    )

@films_bp.route("/assets/steps/<int:assignment_id>/update_status", methods=["POST"])
def update_status(assignment_id):
    db = get_db()
    node_id = request.json.get("node_id")
    node = db.execute("SELECT name FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if node:
        db.execute("""
            UPDATE asset_step_assignments
            SET node_id = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (node_id, node["name"], assignment_id))
        db.commit()
        return jsonify({"success": True})
    return jsonify({"success": False}), 404

@films_bp.route("/assets/steps/<int:assignment_id>/assign_user", methods=["POST"])
def assign_user(assignment_id):
    db = get_db()
    user_id = request.json.get("user_id")
    db.execute("""
        UPDATE asset_step_assignments
        SET assigned_user = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (user_id, assignment_id))
    db.commit()
    return jsonify({"success": True})

@films_bp.route("/films/assets/bulk_edit_assets", methods=["POST"])
def bulk_edit_assets():
    db = get_db()
    asset_ids_raw = request.form.get("asset_ids", "")
    asset_ids = [int(aid.strip()) for aid in asset_ids_raw.split(",") if aid.strip().isdigit()]
    film_id = request.form.get("film_id")
    category = request.form.get("category")

    if not asset_ids:
        return jsonify({"success": False, "message": "No valid asset IDs provided."})

    updates = {}
    due_date = request.form.get("due_date")
    if due_date:
        updates["due_date"] = due_date

    # [OK] Collect step-level updates (assigned, due, node/status)
    step_updates = {}
    for key, value in request.form.items():
        if key.startswith("step_assigned_") or key.startswith("step_due_") or key.startswith("step_status_"):
            try:
                step_id = int(key.split("_")[-1])
            except ValueError:
                continue  # Skip malformed keys

            if step_id not in step_updates:
                step_updates[step_id] = {}

            if key.startswith("step_assigned_") and value.strip():
                step_updates[step_id]["assigned_user"] = value.strip()

            elif key.startswith("step_due_") and value.strip():
                step_updates[step_id]["due_date"] = value.strip()

            elif key.startswith("step_status_") and value.strip():
                step_updates[step_id]["node_id"] = value.strip()

    try:
        for asset_id in asset_ids:
            # Optional global asset-level due date
            if "due_date" in updates:
                db.execute(
                    "UPDATE assets SET due_date = ? WHERE id = ?",
                    (updates["due_date"], asset_id)
                )

            for step_id, step_fields in step_updates.items():
                if not step_fields:
                    continue

                sql_parts = []
                values = []

                for field, val in step_fields.items():
                    sql_parts.append(f"{field} = ?")
                    values.append(val)

                values.append(asset_id)
                values.append(step_id)

                sql = f"""
                    UPDATE asset_step_assignments
                    SET {', '.join(sql_parts)}
                    WHERE asset_id = ? AND step_id = ?
                """
                db.execute(sql, values)

        db.commit()
        return redirect(url_for("films.view_asset_category", film_id=film_id, category=category))

    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e)})

@films_bp.route("/assets/upload_designs", methods=["POST"])
def upload_asset_designs():
    import re
    film_name = request.form.get("film_name")
    asset_category = request.form.get("asset_category")
    asset_name = request.form.get("asset_name")
    files = request.files.getlist("design_files")

    if not film_name or not asset_category or not asset_name:
        return jsonify({"success": False, "message": "Missing film, category, or asset name"}), 400

    # 🔹 Normalize category name
    category_map = {
        "Character/Rigs": "Rigs",
        "Characters/Rigs": "Rigs",
        "Character": "Rigs",
        "Props - 3D": "Props",
        "Props - 2D": "Props",
        "Light Rigs": "LightRigs",
        "Lighting Rigs": "LightRigs",
        "BGs": "BGs",
        "Sets": "Sets",
    }
    safe_category = category_map.get(asset_category, asset_category)

    # 🔹 Clean up names for file system safety
    safe_film = re.sub(r'[<>:"/\\|?*]', "_", film_name)
    safe_asset = re.sub(r'[<>:"/\\|?*]', "_", asset_name)
    safe_category = re.sub(r'[<>:"/\\|?*]', "_", safe_category)

    # 🔹 Construct final folder
    base_path = f"C:/Films/{safe_film}/Assets/{safe_category}/{safe_asset}"
    os.makedirs(base_path, exist_ok=True)

    saved_files = []
    for file in files:
        if file.filename:
            save_path = os.path.join(base_path, file.filename)
            file.save(save_path)
            saved_files.append(file.filename)

    print(f"✅ Saved {len(saved_files)} files to {base_path}")
    return jsonify({"success": True, "message": "Files uploaded successfully", "files": saved_files})



@films_bp.route("/assets/view_designs/<film>/<path:asset_category>/<asset_name>")
def view_asset_designs(film, asset_category, asset_name):
    # Normalize like upload
    category_map = {
        "Character/Rigs": "Rigs",
        "Characters/Rigs": "Rigs",
        "Character": "Rigs",
        "Props - 3D": "Props",
        "Props - 2D": "Props",
        "Light Rigs": "LightRigs",
        "Lighting Rigs": "LightRigs",
        "BGs": "BGs",
        "Sets": "Sets",
    }
    real_category = category_map.get(asset_category, asset_category)

    folder_path = f"C:/Films/{film}/Assets/{real_category}/{asset_name}"
    if not os.path.isdir(folder_path):
        return jsonify({"error": "Not Found"}), 404

    images = [
        f for f in os.listdir(folder_path)
        if f.lower().endswith((".png", ".jpg", ".jpeg"))
    ]

    message = None
    if not images:
        message = "No designs added yet."

    return render_template(
        "films/view_designs.html",
        film=film,
        asset_category=real_category,
        asset_name=asset_name,
        images=images,
        message=message
    )




@films_bp.route("/assets/design_image/<film>/<path:asset_category>/<asset_name>/<path:filename>")
def send_design_image(film, asset_category, asset_name, filename):
    category_map = {
        "Character/Rigs": "Rigs",
        "Characters/Rigs": "Rigs",
        "Character": "Rigs",
        "Props - 3D": "Props",
        "Props - 2D": "Props",
        "Light Rigs": "LightRigs",
        "Lighting Rigs": "LightRigs",
        "BGs": "BGs",
        "Sets": "Sets",
    }
    real_category = category_map.get(asset_category, asset_category)

    folder_path = f"C:/Films/{film}/Assets/{real_category}/{asset_name}"
    return send_from_directory(folder_path, filename)


@films_bp.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({
        "success": False,
        "message": "Files are too large. Maximum total upload size is 200 MB."
    }), 413



# ==========================================================
#   Alternate endpoints: handle by asset_name (for Maya)
# ==========================================================

@films_bp.route("/assets/checkout", methods=["POST"])
def checkout_asset_by_name():
    data = request.get_json()
    asset_name = data.get("asset_name")
    user_name = data.get("user_name")

    if not asset_name or not user_name:
        return jsonify({"error": "Missing asset_name or user_name"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # Get asset_id
    cursor.execute("SELECT id FROM assets WHERE name = ?", (asset_name,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Asset not found"}), 404

    asset_id = row["id"]

    # Get user_id
    cursor.execute("SELECT id FROM users WHERE name = ?", (user_name,))
    urow = cursor.fetchone()
    if not urow:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    user_id = urow["id"]

    # Check if locked
    cursor.execute("SELECT user_id FROM asset_locks WHERE asset_id = ?", (asset_id,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Asset already checked out"}), 400

    cursor.execute("INSERT INTO asset_locks (asset_id, user_id) VALUES (?, ?)", (asset_id, user_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True})


@films_bp.route("/assets/checkin", methods=["POST"])
def checkin_asset_by_name():
    data = request.get_json()
    asset_name = data.get("asset_name")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM assets WHERE name = ?", (asset_name,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Asset not found"}), 404

    asset_id = row["id"]
    cursor.execute("DELETE FROM asset_locks WHERE asset_id = ?", (asset_id,))
    conn.commit()
    conn.close()

    return jsonify({"success": True})


@films_bp.route("/assets/lockstatus", methods=["GET"])
def get_asset_lockstatus_by_name():
    asset_name = request.args.get("asset_name")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM assets WHERE name = ?", (asset_name,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"locked": False})

    asset_id = row["id"]
    cursor.execute("""
        SELECT asset_locks.user_id, users.name
        FROM asset_locks
        LEFT JOIN users ON asset_locks.user_id = users.id
        WHERE asset_id = ?
    """, (asset_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        return jsonify({"locked": True, "user_id": result["user_id"], "user_name": result["name"]})
    else:
        return jsonify({"locked": False})


# ----------------------------------------------------------------------------------------------------------------------
# UTILITY ROUTES
# ----------------------------------------------------------------------------------------------------------------------
@films_bp.route("/api/films/<int:film_id>/progress_summary", methods=["GET"])
def get_progress_summary(film_id):
    db = get_db()

    try:
        # === SHOT PROGRESS ===
        steps = db.execute("""
            SELECT id, name FROM steps
            WHERE parent_id = (SELECT step_id FROM films WHERE id = ?)
            ORDER BY order_num
        """, (film_id,)).fetchall()

        shot_steps = []
        for step in steps:
            status_rows = db.execute("""
                SELECT ssa.status AS status, n.color, COUNT(*) as count
                FROM shot_step_assignments ssa
                JOIN shots s ON ssa.shot_id = s.id
                LEFT JOIN nodes n ON n.name = ssa.status AND n.step_id = ssa.step_id
                WHERE s.scene_id IN (SELECT id FROM scenes WHERE film_id = ?) AND ssa.step_id = ?
                GROUP BY ssa.status, n.color
                ORDER BY count DESC
            """, (film_id, step["id"])).fetchall()

            summary = [
                {"label": row["status"], "value": row["count"], "color": row["color"] or "#ccc"}
                for row in status_rows
            ]

            shot_steps.append({
                "step_id": step["id"],
                "step_name": step["name"],
                "status_summary": summary
            })

        # === SCENE PROGRESS: Thumbnails + FB Thumbnails ===
        scene_rows = db.execute("""
            SELECT s.step_id, st.name AS step_name, s.status, COUNT(*) AS count, n.color
            FROM scene_progress_steps s
            JOIN steps st ON st.id = s.step_id
            LEFT JOIN nodes n ON n.name = s.status AND n.step_id = s.step_id
            WHERE s.scene_id IN (SELECT id FROM scenes WHERE film_id = ?)
              AND st.name IN ('Thumbnails', 'FB Thumbnails')
            GROUP BY s.step_id, st.name, s.status, n.color
        """, (film_id,)).fetchall()

        scene_steps_map = {}
        for row in scene_rows:
            sid = row["step_id"]
            if sid not in scene_steps_map:
                scene_steps_map[sid] = {
                    "step_id": sid,
                    "step_name": row["step_name"],
                    "status_summary": []
                }
            scene_steps_map[sid]["status_summary"].append({
                "label": row["status"],
                "value": row["count"],
                "color": row["color"] or "#ccc"
            })

        # === ASSET PROGRESS (Grouped by Category, Ordered by Step Order) ===
        asset_rows = db.execute("""
            SELECT a.category, sa.step_id, st.name AS step_name, st.order_num, sa.status, COUNT(*) AS count, n.color
            FROM asset_step_assignments sa
            JOIN assets a ON sa.asset_id = a.id
            JOIN steps st ON st.id = sa.step_id
            LEFT JOIN nodes n ON n.name = sa.status AND n.step_id = sa.step_id
            WHERE a.film_id = ?
            GROUP BY a.category, sa.step_id, st.name, st.order_num, sa.status, n.color
            ORDER BY a.category, st.order_num
        """, (film_id,)).fetchall()

        asset_steps = {}
        for row in asset_rows:
            category = row["category"] or "Uncategorized"
            if category not in asset_steps:
                asset_steps[category] = {}

            step_id = row["step_id"]
            if step_id not in asset_steps[category]:
                asset_steps[category][step_id] = {
                    "step_id": step_id,
                    "step_name": row["step_name"],
                    "order_num": row["order_num"],
                    "status_summary": []
                }

            asset_steps[category][step_id]["status_summary"].append({
                "label": row["status"],
                "value": row["count"],
                "color": row["color"] or "#ccc"
            })

        # Sort steps by order_num inside each category before returning
        asset_steps_by_category = {
            cat: sorted(steps.values(), key=lambda s: s["order_num"])
            for cat, steps in asset_steps.items()
        }


        return jsonify({
            "shot_steps": shot_steps,
            "scene_steps": list(scene_steps_map.values()),
            "asset_steps": asset_steps_by_category
        })

    except Exception as e:
        print(f"âŒ Error in progress_summary for film {film_id}: {e}")
        return jsonify({"error": str(e)}), 500

@films_bp.route("/api/config-file-info", methods=["GET"])
def get_config_file_info():
    config_path = r"C:/Cincy/Configs/film_config_v1.json"
    if os.path.exists(config_path):
        mod_time = os.path.getmtime(config_path)
        formatted_date = datetime.fromtimestamp(mod_time).strftime("%B %d, %Y %I:%M %p")
        return jsonify({"exists": True, "modified": formatted_date})
    else:
        return jsonify({"exists": False})

@films_bp.route("/api/generate-dirs", methods=["POST"])
def generate_dirs():
    try:
        script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "film_directory_creator.py"))

        print(" Running script from:", script_path)

        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            check=True
        )
        return jsonify({
            "message": "Directory generation complete.",
            "summary": result.stdout.strip()
        })
    except subprocess.CalledProcessError as e:
        print(" Folder script failed:")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        return jsonify({
            "error": "Folder generation failed.",
            "stdout": e.stdout.strip(),
            "stderr": e.stderr.strip()
        }), 500


@films_bp.route("/api/film/dashboard_data", methods=["GET"])
@login_required
def get_dashboard_data():
    user_id = session.get("view_as_user_id") or session.get("user_id")
    user_name = session.get("username")

    conn = get_db()

    films = conn.execute("""
        SELECT DISTINCT f.id, f.name, f.step_id AS film_step_id
        FROM films f
        JOIN film_crew fc ON fc.film_id = f.id
        WHERE fc.user_id = ? AND f.archived = 0
    """, (user_id,)).fetchall()

    result = []

    for film in films:
        shots = []
        assignment_lookup = {}

        # Which scenes in this film have an approved (locked) scene
        # Layout -- gates whether the shot-level Layout OPEN button below
        # is clickable, same "scene_layout_done" check CapstoneLayout.py's
        # run_shot() itself enforces server-side; this is just what makes
        # the dashboard button reflect that truthfully instead of always
        # showing enabled.
        done_scene_ids = set()
        layout_step_row = conn.execute(
            "SELECT id FROM steps WHERE parent_id = ? AND name = 'Layout'",
            (film["film_step_id"],)
        ).fetchone()
        if layout_step_row:
            done_scene_ids = {
                row["entity_id"] for row in conn.execute("""
                    SELECT sl.entity_id
                    FROM step_locks sl
                    JOIN scenes sc ON sc.id = sl.entity_id
                    WHERE sl.entity_type = 'scene_step' AND sl.step_id = ?
                      AND sl.locked = 1 AND sc.film_id = ?
                """, (layout_step_row["id"], film["id"])).fetchall()
            }

        # Per-shot gates for Layout -> Blocking -> Animation -> Lighting.
        # Each is THIS SHOT's own prior step being Approved or CUT -- never
        # scene-wide, never dependent on sibling shots. Read from
        # shot_step_assignments.status rather than step_locks: CUT is set
        # through the generic status-dropdown endpoint (update_scene_status()
        # in review_routes.py), which never touches step_locks, and there's
        # no dedicated "Approve" button anywhere in the UI for any of these
        # steps -- coordinators approve via the plain status dropdown, which
        # only ever writes shot_step_assignments. A lock-based check would
        # never see any of these approvals. Matches the identical gates
        # capstone_routes.py enforces server-side when Maya actually opens
        # each file (shot_blocking_context()/shot_animation_context()/
        # shot_lighting_context()).
        def _approved_shot_ids(step_name):
            step_row = conn.execute(
                "SELECT id FROM steps WHERE parent_id = ? AND name = ?",
                (film["film_step_id"], step_name)
            ).fetchone()
            if not step_row:
                return set()
            return {
                row["shot_id"] for row in conn.execute("""
                    SELECT ssa.shot_id
                    FROM shot_step_assignments ssa
                    JOIN shots s ON s.id = ssa.shot_id
                    JOIN scenes sc ON sc.id = s.scene_id
                    WHERE ssa.step_id = ? AND sc.film_id = ?
                      AND LOWER(TRIM(ssa.status)) IN ('approved', 'cut')
                """, (step_row["id"], film["id"])).fetchall()
            }

        layout_approved_shot_ids = _approved_shot_ids("Layout")
        blocking_approved_shot_ids = _approved_shot_ids("Blocking")
        animation_approved_shot_ids = _approved_shot_ids("Animation")

        # Get scene-level assignments (e.g., thumbnails)
        scene_steps = conn.execute("""
            SELECT sps.scene_id, sc.scene_number, sps.step_id, sps.status, sps.due_date,
                   st.name AS step_name
            FROM scene_progress_steps sps
            JOIN steps st ON st.id = sps.step_id
            JOIN scenes sc ON sc.id = sps.scene_id
            WHERE sps.assigned_to = ? AND sc.film_id = ?
        """, (user_id, film["id"])).fetchall()

        for step in scene_steps:
                key = (step["scene_id"], step["step_id"])
                assignment_lookup[key] = dict(step)

        # Get shot-level assignments
        shot_steps = conn.execute("""
        SELECT sa.shot_id,
            s.shot_number AS shot_number,
            sc.scene_number,
            sa.step_id,
            sa.status,
            sa.due_date,
            st.name AS step_name,
            sc.id AS scene_id
            FROM shot_step_assignments sa
            JOIN steps st ON st.id = sa.step_id
            JOIN shots s ON s.id = sa.shot_id
            JOIN scenes sc ON sc.id = s.scene_id
            WHERE sa.assigned_to = ? AND sc.film_id = ?
        """, (user_id, film["id"])).fetchall()


        for step in shot_steps:
            assignment_lookup[(step["shot_id"], step["step_id"])] = dict(step)

        # Get dropdown options for steps
        steps_map = {}
        all_step_ids = list({step_id for (_, step_id) in assignment_lookup})
        if all_step_ids:
            placeholder = ",".join(["?"] * len(all_step_ids))
            node_rows = conn.execute(f"""
                SELECT step_id, name, color
                FROM nodes
                WHERE step_id IN ({placeholder})
            """, all_step_ids).fetchall()

            for row in node_rows:
                steps_map.setdefault(row["step_id"], []).append({
                    "name": row["name"],
                    "color": row["color"]
                })

        # Prepare final data
        for (shot_id, step_id), assign in assignment_lookup.items():
            if assign["status"].lower() == "approved":
                continue

            step_data = {
                "step_id": step_id,
                "step_name": assign["step_name"],
                "status": assign["status"],
                "status_color": next(
                    (opt["color"] for opt in steps_map.get(step_id, []) if opt["name"] == assign["status"]),
                    "#cccccc"
                ),
                "dropdown_options": steps_map.get(step_id, []),
                "due_date": assign["due_date"],
                "assigned_to": user_name
            }

            scene_id = assign["scene_id"] if "scene_id" in assign.keys() else None


            # Determine key: either by shot_id or scene_id for thumbnails
            entry_key = shot_id if shot_id is not None else f"scene_{scene_id}"

            # Check if this shot or scene entry already exists
            existing_entry = next((s for s in shots if s.get("key") == entry_key), None)

            if existing_entry:
                existing_entry["steps"].append(step_data)
            else:
                shot_entry = {
                    "key": entry_key,  # ðŸ‘ˆ temp internal key to identify uniqueness
                    "shot_id": shot_id,
                    "shot_number": assign.get("shot_number", "-") if shot_id is not None else "-",
                    "scene_number": assign["scene_number"],
                    "scene_id": scene_id,
                    "scene_layout_done": scene_id in done_scene_ids,
                    "shot_layout_approved": shot_id in layout_approved_shot_ids,
                    "shot_blocking_approved": shot_id in blocking_approved_shot_ids,
                    "shot_animation_approved": shot_id in animation_approved_shot_ids,
                    "steps": [step_data]
                }
                shots.append(shot_entry)


        result.append({
            "film_id": film["id"],
            "title": film["name"],
            "shots": shots
        })

    return jsonify(result)

@films_bp.route("/<int:film_id>/notes", methods=["GET"])
def view_notes(film_id):
    db = get_db()
    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    film_name = film["name"]
    notes_path = f"C:/Films/{film_name}/Notes"

    notes_files = []
    if os.path.isdir(notes_path):
        notes_files = [
            f for f in os.listdir(notes_path)
            if f.lower().endswith((".doc", ".docx", ".pdf", ".txt"))
        ]

    scripts_path = f"C:/Films/{film_name}/Scripts"
    script_files = []
    if os.path.isdir(scripts_path):
        script_files = [
            f for f in os.listdir(scripts_path)
            if f.lower().endswith((".pdf", ".doc", ".docx", ".txt"))
        ]


    return render_template("films/view_notes.html",
                        film=film,
                        notes_files=notes_files,
                        script_files=script_files,
                        notes_path=notes_path)


@films_bp.route("/<int:film_id>/notes/<path:filename>")
def download_note_file(film_id, filename):
    db = get_db()
    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    film_name = film["name"]
    notes_path = f"C:/Films/{film_name}/Notes"

    if not os.path.exists(os.path.join(notes_path, filename)):
        return "File not found", 404

    return send_from_directory(notes_path, filename, as_attachment=False)


@films_bp.route("/<int:film_id>/notes/upload", methods=["POST"])
def upload_note_file(film_id):
    db = get_db()
    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    film_name = film["name"]
    notes_path = f"C:/Films/{film_name}/Notes"
    os.makedirs(notes_path, exist_ok=True)

    file = request.files.get("note_file")
    if not file or file.filename == "":
        flash("No file selected for upload", "error")
        return redirect(url_for("films.view_notes", film_id=film_id))

    save_path = os.path.join(notes_path, file.filename)
    file.save(save_path)

    flash("Note uploaded successfully", "success")
    return redirect(url_for("films.view_notes", film_id=film_id))


@films_bp.route("/<int:film_id>/scripts", methods=["GET"])
def view_scripts(film_id):
    db = get_db()
    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    film_name = film["name"]
    scripts_path = f"C:/Films/{film_name}/Scripts"

    script_files = []
    if os.path.isdir(scripts_path):
        script_files = [
            f for f in os.listdir(scripts_path)
            if f.lower().endswith((".pdf", ".doc", ".docx", ".txt"))
        ]

    return render_template("films/view_notes.html",
                           film=film,
                           notes_files=[],
                           script_files=script_files)


@films_bp.route("/<int:film_id>/scripts/<path:filename>")
def download_script_file(film_id, filename):
    db = get_db()
    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    film_name = film["name"]
    scripts_path = f"C:/Films/{film_name}/Scripts"

    if not os.path.exists(os.path.join(scripts_path, filename)):
        return "File not found", 404

    return send_from_directory(scripts_path, filename, as_attachment=False)


@films_bp.route("/<int:film_id>/scripts/upload", methods=["POST"])
def upload_script_file(film_id):
    db = get_db()
    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    film_name = film["name"]
    scripts_path = f"C:/Films/{film_name}/Scripts"
    os.makedirs(scripts_path, exist_ok=True)

    file = request.files.get("script_file")
    if not file or file.filename == "":
        flash("No file selected for upload", "error")
        return redirect(url_for("films.view_notes", film_id=film_id))

    save_path = os.path.join(scripts_path, file.filename)
    file.save(save_path)

    flash("Script uploaded successfully", "success")
    return redirect(url_for("films.view_notes", film_id=film_id))


@films_bp.route("/<int:film_id>/upload_note_or_script", methods=["POST"])
def upload_note_or_script(film_id):
    db = get_db()
    film = db.execute("SELECT * FROM films WHERE id = ?", (film_id,)).fetchone()
    if not film:
        return "Film not found", 404

    film_name = film["name"]
    action = request.form.get("action")
    file = request.files.get("shared_file")

    if not file or file.filename == "":
        flash("No file selected for upload", "error")
        return redirect(url_for("films.view_notes", film_id=film_id))

    if action == "note":
        dest_folder = f"C:/Films/{film_name}/Notes"
        flash_msg = "Note uploaded successfully"
    elif action == "script":
        dest_folder = f"C:/Films/{film_name}/Scripts"
        flash_msg = "Script uploaded successfully"
    else:
        flash("Unknown upload type", "error")
        return redirect(url_for("films.view_notes", film_id=film_id))

    os.makedirs(dest_folder, exist_ok=True)
    save_path = os.path.join(dest_folder, file.filename)
    file.save(save_path)

    flash(flash_msg, "success")
    return redirect(url_for("films.view_notes", film_id=film_id))


# ----------------------------------------------------------------------------------------------------------------------
# ASSIGN ROUTES
# ----------------------------------------------------------------------------------------------------------------------



@films_bp.route("/films/<int:film_id>/assign", methods=["GET"])
def assign_film(film_id):
    db = get_db()

    # 🎬 Get film
    film = db.execute(
        "SELECT id, name FROM films WHERE id = ?", (film_id,)
    ).fetchone()
    if film is None:
        abort(404)

    def normalize_assigned(value):
        if value is None:
            return None
        try:
            return int(value)
        except:
            return None


    def fetch_shots_for_step(step_name):
        return db.execute("""
            SELECT 
                sh.id,
                sh.scene_id,
                sc.scene_number,
                sh.shot_number,
                CAST(ssa.assigned_to AS INTEGER) AS assigned_to,
                ssa.due_date,
                ssa.status,
                ssa.step_id,
                ssa.difficulty   -- ← ADD THIS LINE
            FROM shots sh
            JOIN scenes sc ON sc.id = sh.scene_id
            JOIN shot_step_assignments ssa ON ssa.shot_id = sh.id
            JOIN steps st ON st.id = ssa.step_id
            WHERE sc.film_id = ?
            AND st.name = ?
            ORDER BY sc.scene_number, sh.shot_number
        """, (film_id, step_name)).fetchall()

    def fetch_all_shots_for_step(step_name):
        return db.execute("""
            SELECT 
                sh.id,
                sh.scene_id,
                sc.scene_number,
                sh.shot_number,
                CAST(ssa.assigned_to AS INTEGER) AS assigned_to,
                ssa.due_date,
                ssa.status,
                ssa.step_id,
                ssa.difficulty
            FROM shots sh
            JOIN scenes sc ON sc.id = sh.scene_id
            JOIN shot_step_assignments ssa ON ssa.shot_id = sh.id
            JOIN steps st ON st.id = ssa.step_id
            WHERE st.name = ?
            ORDER BY sc.scene_number, sh.shot_number
        """, (step_name,)).fetchall()

    # -----------------------------------------
    # 1️⃣ ARTISTS (crew + anyone already assigned)
    # -----------------------------------------
    artists = db.execute("""
        SELECT DISTINCT u.id, u.name
        FROM users u
        WHERE u.id IN (

            -- Any artist assigned to SCENE-LEVEL thumbnails
            SELECT sps.assigned_to
            FROM scene_progress_steps sps
            JOIN scenes sc ON sc.id = sps.scene_id
            WHERE sc.film_id = :film_id
            AND sps.assigned_to IS NOT NULL

            UNION

            -- Any artist assigned to SHOT-LEVEL steps
            SELECT ssa.assigned_to
            FROM shot_step_assignments ssa
            JOIN shots sh ON sh.id = ssa.shot_id
            JOIN scenes sc2 ON sc2.id = sh.scene_id
            WHERE sc2.film_id = :film_id
            AND ssa.assigned_to IS NOT NULL

            UNION

            -- ALSO include crew, so coordinators can assign new work
            SELECT fc.user_id
            FROM film_crew fc
            WHERE fc.film_id = :film_id

        )
        ORDER BY u.name
    """, {"film_id": film_id}).fetchall()



    # 2️⃣ SCENES + THUMBNAIL ASSIGNMENTS

    THUMBNAIL_STEP_ID = 327

    scenes = db.execute("""
        SELECT 
            sc.id AS scene_id,
            sc.scene_number,
            sps.assigned_to AS thumb_assigned_to,
            sps.due_date AS thumb_due_date,
            sps.status AS thumb_status,
            sps.difficulty AS difficulty
        FROM scenes sc
        LEFT JOIN scene_progress_steps sps
            ON sps.scene_id = sc.id
            AND sps.step_id = ?
        WHERE sc.film_id = ?
        ORDER BY sc.scene_number
    """, (THUMBNAIL_STEP_ID, film_id)).fetchall()


    # -----------------------------------------
    # 3️⃣ SHOTS BY PHASE (NOW USING YOUR FUNCTION)
    # -----------------------------------------
    storyboard_shots = fetch_shots_for_step("Storyboards")
    layout_shots = fetch_shots_for_step("Layout")
    anim_shots = fetch_shots_for_step("Animation")
    print("ANIM SHOTS DEBUG:")
    for s in anim_shots:
        print(dict(s))
    fx_shots = fetch_shots_for_step("FX")
    light_shots = fetch_shots_for_step("Lighting")
    comp_shots = fetch_shots_for_step("Compositing")

    # GLOBAL SHOTS (ALL FILMS) — FOR LOAD ONLY
    global_storyboard_shots = fetch_all_shots_for_step("Storyboards")
    global_layout_shots     = fetch_all_shots_for_step("Layout")
    global_anim_shots       = fetch_all_shots_for_step("Animation")
    global_fx_shots         = fetch_all_shots_for_step("FX")
    global_light_shots      = fetch_all_shots_for_step("Lighting")
    global_comp_shots       = fetch_all_shots_for_step("Compositing")
    # -----------------------------------------------------------
    # HELPER FUNCTIONS (SAFE FOR sqlite3.Row + dict)
    # -----------------------------------------------------------
    def to_dict(shot):
        """Converts sqlite3.Row to dict, leaves dicts untouched."""
        if not isinstance(shot, dict):
            return dict(shot)
        return shot

    def is_approved(shot):
        if not isinstance(shot, dict):
            shot = dict(shot)
        return (shot.get("status") or "").lower() == "approved"


    def is_standby(shot):
        if not isinstance(shot, dict):
            shot = dict(shot)
        return (shot.get("status") or "").lower() == "standby"


    def get_assigned(shot):
        if not isinstance(shot, dict):
            shot = dict(shot)
        return normalize_assigned(shot.get("assigned_to"))


    def is_cut_shot(shot):
        # Convert sqlite.Row to dict
        if not isinstance(shot, dict):
            shot = dict(shot)

        # 1️⃣ Shot-level CUT (the thing your DB actually uses)
        shot_status = (shot.get("status") or "").lower()
        if shot_status == "cut":
            return True

        # 2️⃣ Node-level CUT (future-proofing)
        nodes = shot.get("nodes") or []
        for node in nodes:
            step = (node.get("step") or "").upper()
            status = (node.get("status") or "").upper()
            if step == "CUT" or status == "CUT":
                return True

        return False



    # -----------------------------------------------------------
    # ARTIST LOAD CALCULATION (CLEAN + UNIFIED)
    # -----------------------------------------------------------
    artist_load = {}

    # Phase difficulty mapping
    PHASES = [
        ("Storyboards", global_storyboard_shots, 1),
        ("Layout",       global_layout_shots,      1),
        ("Animation",    global_anim_shots,        3),
        ("FX",           global_fx_shots,          2),
        ("Lighting",     global_light_shots,       2),
        ("Compositing",  global_comp_shots,        2),
    ]

    # Reset artist load (keeps existing initialization)
    
    for a in artists:
        artist_load[a["id"]] = {
            "name": a["name"],
            "role": None,
            "tasks": 0,
            "thumb_diff": 0,
            "anim_diff": 0,
            "deadline_load": 0,
            "total_load": 0,
            "status": "Available",
        }

    # Count load by shot phase
    for phase_name, shots_list, base_diff in PHASES:
        for shot in shots_list:

            if not isinstance(shot, dict):
                shot = dict(shot)

            # Skip CUT
            if is_cut_shot(shot):
                continue

            artist_id = get_assigned(shot)
            if not artist_id or artist_id not in artist_load:
                continue

            # Skip approved
            if is_approved(shot):
                continue

            # Count tasks
            artist_load[artist_id]["tasks"] += 1

            # 🔥 USE REAL DIFFICULTY
            shot_diff = shot.get("difficulty") or base_diff

            if phase_name == "Animation":
                artist_load[artist_id]["anim_diff"] += shot_diff
            elif phase_name == "Storyboards":
                artist_load[artist_id]["thumb_diff"] += shot_diff

            artist_load[artist_id]["total_load"] += shot_diff


    # -----------------------------------------------------------
    # THUMBNAILS — USE REAL DIFFICULTY
    # -----------------------------------------------------------
    for scene in scenes:
        artist_id = normalize_assigned(scene["thumb_assigned_to"])
        if not artist_id or artist_id not in artist_load:
            continue

        # Skip approved thumbnails
        if (scene["thumb_status"] or "").lower() == "approved":
            continue

        diff = scene["difficulty"] or 1

        artist_load[artist_id]["tasks"] += 1
        artist_load[artist_id]["thumb_diff"] += diff
        artist_load[artist_id]["total_load"] += diff


    # -----------------------------------------------------------
    # Deadline load = how many shots have due dates approaching
    # -----------------------------------------------------------

    import datetime
    today = datetime.date.today()

    for phase_list in [storyboard_shots, layout_shots, anim_shots, fx_shots, light_shots, comp_shots]:
        for shot in phase_list:

            # normalize assigned_to (string → int)
            artist_id = None
            if shot["assigned_to"] is not None:
                try:
                    artist_id = int(shot["assigned_to"])
                except:
                    artist_id = None

            if (
                artist_id
                and shot["due_date"]
                and (shot["status"] or "").lower() != "approved"
            ):
                try:
                    due = datetime.date.fromisoformat(shot["due_date"])
                    days_left = (due - today).days

                    # Shots due within 7 days increase load
                    if days_left <= 7:
                        artist_load[artist_id]["deadline_load"] += 1
                        artist_load[artist_id]["total_load"] += 1

                except Exception as e:
                    print("Deadline load error:", e)



    # -----------------------------------------------------------
    # Determine status label based on total load
    # -----------------------------------------------------------

    for a_id, data in artist_load.items():
        load = data["total_load"]

        if load == 0:
            data["status"] = "Available"
        elif load < 6:
            data["status"] = "Low"
        elif load < 12:
            data["status"] = "Medium"
        else:
            data["status"] = "High"

    # -----------------------------------------------
    # UNIQUE SHOT COUNTING (correct totals)
    # -----------------------------------------------

    # Combine all steps into one big list
    all_shots = (
        list(storyboard_shots)
        + list(layout_shots)
        + list(anim_shots)
        + list(fx_shots)
        + list(light_shots)
        + list(comp_shots)
    )

    # Unique shots by shot_id
    unique_shots = {}
    for shot in all_shots:
        # Convert sqlite row to dict
        if not isinstance(shot, dict):
            shot = dict(shot)

        sid = shot.get("id") or shot.get("shot_id")
        if not sid:
            continue

        # Skip CUT
        if is_cut_shot(shot):
            continue

        unique_shots[sid] = shot

    # Helper: should this shot count?
    def valid_total_shot(shot):
        status = (shot.get("status") or "").lower()
        if status == "standby":
            return False
        return True

    total_shots = sum(
        1 for s in unique_shots.values() if valid_total_shot(s)
    )

    total_unassigned = sum(
        1 for s in unique_shots.values()
        if valid_total_shot(s) and not s.get("assigned_to")
    )

    # -----------------------------------------
    # TOTAL SHOTS + UNASSIGNED (skip approved)
    # -----------------------------------------
    total_shots = 0
    total_unassigned = 0

    for _, shots_list, _ in PHASES:
        for shot in shots_list:

            # convert sqlite row → dict
            if not isinstance(shot, dict):
                shot = dict(shot)

            # skip CUT
            if is_cut_shot(shot):
                continue

            status = (shot.get("status") or "").lower()

            # skip Standby (not real yet)
            if status == "standby":
                continue

            # 🔥 skip Approved (do not count in totals)
            if status == "approved":
                continue

            # count the task
            total_shots += 1

            # count unassigned (ONLY non-approved, non-standby, non-cut)
            if not get_assigned(shot):
                total_unassigned += 1



    phase_data = {
        "storyboard_count": len(storyboard_shots),
        "layout_count": len(layout_shots),
        "anim_count": len(anim_shots),
        "fx_count": len(fx_shots),
        "light_count": len(light_shots),
        "comp_count": len(comp_shots),

        "storyboard_assigned": sum(1 for s in storyboard_shots if s["assigned_to"]),
        "layout_assigned": sum(1 for s in layout_shots if s["assigned_to"]),
        "anim_assigned": sum(1 for s in anim_shots if s["assigned_to"]),
        "fx_assigned": sum(1 for s in fx_shots if s["assigned_to"]),
        "light_assigned": sum(1 for s in light_shots if s["assigned_to"]),
        "comp_assigned": sum(1 for s in comp_shots if s["assigned_to"]),

        "thumb_scene_count": len(scenes),
        "thumbs_assigned": sum(1 for s in scenes if s["thumb_assigned_to"]),

        "total_shots": total_shots,
        "total_unassigned": total_unassigned,


    }


    return render_template(
        "films/assign.html",
        film=film,
        artists=artists,
        scenes=scenes,
        storyboard_shots=storyboard_shots,
        layout_shots=layout_shots,
        anim_shots=anim_shots,
        fx_shots=fx_shots,
        light_shots=light_shots,
        comp_shots=comp_shots,
        phase_data=phase_data,
        artist_load=artist_load
    )


@films_bp.route("/films/<int:film_id>/assign/save", methods=["POST"])
def save_film_assignments(film_id):
    db = get_db()
    data = request.json  # we will send JSON from the page

    # ------------------------------
    # 1️⃣ Save Thumbnail Assignments
    # ------------------------------
    thumbnails = data.get("thumbnails", [])
    for item in thumbnails:
        scene_id = item.get("scene_id")
        artist_id = item.get("assigned_to")
        due = item.get("due_date")

        # Update scene_progress_steps
        db.execute("""
            UPDATE scene_progress_steps
            SET assigned_to = ?, due_date = ?
            WHERE scene_id = ?
              AND step_id = 327
        """, (artist_id, due, scene_id))

    # ------------------------------
    # 2️⃣ Save Shot Assignments (all phases)
    # ------------------------------
    shots = data.get("shots", [])
    for item in shots:
        shot_id = item.get("shot_id")
        step_id = item.get("step_id")
        artist_id = item.get("assigned_to")
        due = item.get("due_date")

        db.execute("""
            UPDATE shot_step_assignments
            SET assigned_to = ?, due_date = ?
            WHERE shot_id = ?
              AND step_id = ?
        """, (artist_id, due, shot_id, step_id))

    db.commit()

    return jsonify({"success": True})


@films_bp.route("/api/scenes/<int:scene_id>/thumbnail/update", methods=["POST"])
def update_thumbnail_assignment(scene_id):
    db = get_db()
    data = request.get_json()

    difficulty = data.get("difficulty")
    assigned_to = data.get("assigned_to")
    due_date = data.get("due_date")

    THUMBNAIL_STEP_ID = 327  # your thumbnail step id

    # Ensure the record exists
    existing = db.execute("""
        SELECT id FROM scene_progress_steps
        WHERE scene_id = ? AND step_id = ?
    """, (scene_id, THUMBNAIL_STEP_ID)).fetchone()

    if existing:
        # Update it
        db.execute("""
            UPDATE scene_progress_steps
            SET assigned_to = ?, due_date = ?, difficulty = ?
            WHERE scene_id = ? AND step_id = ?
        """, (assigned_to, due_date, difficulty, scene_id, THUMBNAIL_STEP_ID))

    else:
        # Insert it
        db.execute("""
            INSERT INTO scene_progress_steps (scene_id, step_id, assigned_to, due_date, difficulty)
            VALUES (?, ?, ?, ?, ?)
        """, (scene_id, THUMBNAIL_STEP_ID, assigned_to, due_date, difficulty))

    db.commit()

    return jsonify({"success": True})


@films_bp.route("/api/finalize_storyboard/<scene_id>", methods=["POST"])
def finalize_storyboard(scene_id):
    import os, shutil

    conn = get_db()
    cur = conn.cursor()

    # FIX: films table uses 'name', not 'film_name'
    cur.execute("""
        SELECT f.name AS film_name, s.scene_number
        FROM scenes s
        JOIN films f ON f.id = s.film_id
        WHERE s.id = ?
    """, (scene_id,))
    row = cur.fetchone()
    if not row:
        return jsonify({"error": "Scene not found"}), 404

    film = row["film_name"]
    scene_num = row["scene_number"].zfill(3)

    base_dir = os.getenv("FILMS_ROOT", r"\\GAAAP1PRD01W\Films")
    scene_dir = os.path.join(base_dir, film, scene_num)

    # Find SB file
    sb_file = None
    for f in os.listdir(scene_dir):
        if "_SB_" in f and f.endswith(".webm") and "_R" not in f:
            sb_file = f
            break

    if not sb_file:
        return jsonify({"error": "No storyboard file found"}), 404

    src = os.path.join(scene_dir, sb_file)
    dst = src.replace(".webm", "_R.webm")

    os.rename(src, dst)

    return jsonify({
        "message": "Storyboard finalized",
        "reviewed_file_path": dst
    })

# ----------------------------------------------------------------------------------------------------------------------
# AI FILTER MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------


@films_bp.route("/ai-filter", methods=["POST"])
def ai_filter_route():
    user_query = request.form.get("query", "")
    if not user_query:
        return jsonify({"error": "No query provided"}), 400

    system_prompt = """
You are a helpful assistant for a film production tracker. 
Your job is to translate user queries into JSON filters.
Return only a JSON object with keys like: step_names, statuses, due_within.

Examples:
"Show me retakes in storyboard" â†’ {"step_names": ["Storyboard"], "statuses": ["Retake"]}
"What needs approval this week?" â†’ {"statuses": ["Submitted", "Needs Approval"], "due_within": "this_week"}
"""

    # ðŸ”‘ Replace with your OpenAI key
    openai.api_key = os.getenv("OPENAI_API_KEY")

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query}
            ],
            temperature=0.2
        )
        filter_json = json.loads(response.choices[0].message.content)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # [OK] Example SQL filter (super simple for now)
    step_filter = " AND ".join(["step_name = ?" for _ in filter_json.get("step_names", [])])
    status_filter = " AND ".join(["status = ?" for _ in filter_json.get("statuses", [])])

    query = f"""
        SELECT * FROM scenes_view WHERE 1=1
        {"AND (" + step_filter + ")" if step_filter else ""}
        {"AND (" + status_filter + ")" if status_filter else ""}
    """

    args = filter_json.get("step_names", []) + filter_json.get("statuses", [])
    db = get_db()
    scenes = db.execute(query, args).fetchall()

    return render_template("partials/scene_rows.html", scenes=scenes)

@films_bp.route("/<int:film_id>/ai-filter", methods=["POST"])
def ai_scene_filter(film_id):
    query = request.json.get("query", "").lower()
    db = get_db()

    # 1. Load all scenes for film
    all_scenes = db.execute("""
        SELECT 
            sc.id, sc.scene_number, sc.start_date, sc.due_date,
            f.name AS film_name,
            w.name AS workflow_name
        FROM scenes sc
        LEFT JOIN films f ON sc.film_id = f.id
        LEFT JOIN steps w ON sc.workflow_id = w.id
        WHERE sc.film_id = ?
        ORDER BY sc.scene_number ASC
    """, (film_id,)).fetchall()

    filtered = []
    today = datetime.now(timezone.utc).date()


    # 2. Very basic NLP-like rule match
    for s in all_scenes:
        scene = dict(s)
        start = date.fromisoformat(scene["start_date"]) if scene["start_date"] else None
        due = date.fromisoformat(scene["due_date"]) if scene["due_date"] else None

        match = False
        if "due this week" in query and due and (0 <= (due - today).days <= 7):
            match = True
        elif "due this month" in query and due and due.month == today.month and due.year == today.year:
            match = True
        elif "starts this week" in query and start and (0 <= (start - today).days <= 7):
            match = True
        elif "starts this month" in query and start and start.month == today.month and start.year == today.year:
            match = True
        elif "all" in query or "everything" in query or query.strip() == "":
            match = True

        if match:
            scene["status_summary"] = "â€”"  # placeholder, same as base view
            filtered.append(scene)

    # 3. Return rendered partial for dynamic replacement
    return render_template("films/scene_rows.html", scenes=filtered)

@films_bp.route("/api/shots/<int:shot_id>/animation/update", methods=["POST"])
def update_animation_shot(shot_id):

    data = request.get_json()

    difficulty = data.get("difficulty")
    assigned_to = data.get("assigned_to")
    due_date = data.get("due_date")
    step_id = data.get("step_id")   # ← NEW

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE shot_step_assignments
        SET difficulty = ?,
            assigned_to = ?,
            due_date = ?
        WHERE shot_id = ?
          AND step_id = ?
    """, (difficulty, assigned_to, due_date, shot_id, step_id))

    conn.commit()
    conn.close()

    return jsonify({"status": "success"})
