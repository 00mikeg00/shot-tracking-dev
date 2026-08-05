from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for
import os
import json
import re
from app.database.db import get_db
from app.utils.utils import find_matching_asset_file
import logging


logging.basicConfig(level=logging.DEBUG)

film_config_bp = Blueprint("film_config", __name__)

# --- Config Paths ---
CONFIG_DIR = "C:/Cincy/Configs"
FINAL_CONFIG_PATH = os.path.join(CONFIG_DIR, "film_config.json")
DRAFT_CONFIG_PATH = os.path.join(CONFIG_DIR, "_draft_film_config.json")

os.makedirs(CONFIG_DIR, exist_ok=True)


def generate_film_id(title):
    """Generate a slug-based, unique film ID from the title."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", title.lower()).strip("_")

# ----------------------------------------------------------------------------------------------------------------------
# Getting information
# ----------------------------------------------------------------------------------------------------------------------

@film_config_bp.route("/semesters", methods=["GET"])
def get_semesters():
    try:
        # Mock data for now, replace with actual DB call
        semesters = [
            {"id": 1, "year": 2025, "term": "Spring"},
            {"id": 2, "year": 2025, "term": "Summer"},
            {"id": 3, "year": 2025, "term": "Fall"}
        ]
        return jsonify(semesters)
    except Exception as e:
        print(f"âŒ Failed to fetch semesters: {e}")
        return jsonify({"error": "Failed to fetch semesters"}), 500

@film_config_bp.route("/api/list", methods=["GET"])
def list_films():
    try:
        conn = get_db()
        films = conn.execute("""
            SELECT id, name
            FROM films
            ORDER BY name
        """).fetchall()

        # Convert to JSON-friendly format
        film_list = [dict(row) for row in films]
        return jsonify(film_list)

    except Exception as e:
        print(f"âŒ Failed to fetch films: {e}")
        return jsonify({"error": "Failed to fetch films"}), 500

@film_config_bp.route("/films", methods=["GET"])
def view_films():
    try:
        with open(CONFIG_PATH, "r") as f:
            film_data = json.load(f)
    except FileNotFoundError:
        film_data = {}
    return render_template("films.html", films=film_data)

@film_config_bp.route("/<int:film_id>/scenes", methods=["GET"])
def get_scenes(film_id):
    try:
        conn = get_db()
        scenes = conn.execute("""
            SELECT id, scene_number, description, start_date, due_date
            FROM scenes
            WHERE film_id = ?
            ORDER BY scene_number
        """, (film_id,)).fetchall()

        # Convert to JSON-friendly format
        scene_list = [dict(row) for row in scenes]

        # Return an empty list if no scenes are found
        if not scene_list:
            print(f"âš ï¸ No scenes found for film ID {film_id}")
            return jsonify([]), 200

        return jsonify(scene_list)

    except Exception as e:
        print(f"âŒ Failed to fetch scenes for film {film_id}: {e}")
        return jsonify({"error": f"Failed to fetch scenes for film {film_id}"}), 500

@film_config_bp.route("/scenes/<int:scene_id>/shots", methods=["GET"])
def get_shots(scene_id):
    try:
        conn = get_db()
        shots = conn.execute("""
            SELECT id, shot_number, assigned_to, start_date, due_date, description
            FROM shots
            WHERE scene_id = ?
            ORDER BY shot_number
        """, (scene_id,)).fetchall()

        # Convert to JSON-friendly format
        shot_list = [dict(row) for row in shots]
        return jsonify(shot_list)

    except Exception as e:
        print(f"âŒ Failed to fetch shots for scene {scene_id}: {e}")
        return jsonify({"error": f"Failed to fetch shots for scene {scene_id}"}), 500

@film_config_bp.route("/assets/<int:film_id>", methods=["GET"])
def get_assets(film_id):
    try:
        conn = get_db()
        assets = conn.execute("""
            SELECT id, name, category, file_path
            FROM assets
            WHERE film_id = ?
        """, (film_id,)).fetchall()

        return jsonify([dict(a) for a in assets])
    except Exception as e:
        print(f"âŒ Failed to fetch assets for film {film_id}: {e}")
        return jsonify({"error": "Failed to fetch assets"}), 500

@film_config_bp.route("/assets/<int:film_id>/<path:asset_type>", methods=["GET"])
def get_assets_by_type(film_id, asset_type):
    """
    Return assets from the database filtered by film and category.
    Handles categories like 'Character/Rigs' correctly.
    """
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT id, name, category, file_path
            FROM assets
            WHERE film_id = ?
              AND (category = ? OR category LIKE ?)
            ORDER BY name
        """, (film_id, asset_type, f"%{asset_type}%")).fetchall()

        if not rows:
            return jsonify([])

        return jsonify([dict(row) for row in rows])
    except Exception as e:
        print(f"❌ Error fetching assets for film {film_id}, type '{asset_type}': {e}")
        return jsonify({"error": str(e)}), 500


# ----------------------------------------------------------------------------------------------------------------------
# ADDING
# ----------------------------------------------------------------------------------------------------------------------

@film_config_bp.route("/api/add", methods=["POST"])
def add_film():
    try:
        data = request.get_json()
        name = data.get("name", "").strip()

        if not name:
            return jsonify({"error": "Film name is required."}), 400

        conn = get_db()
        cursor = conn.execute("""
            INSERT INTO films (name)
            VALUES (?)
        """, (name,))
        conn.commit()

        # Get the new film ID
        film_id = cursor.lastrowid

        return jsonify({"id": film_id, "name": name})

    except Exception as e:
        print(f"âŒ Failed to add film: {e}")
        return jsonify({"error": f"Failed to add film: {e}"}), 500


@film_config_bp.route("/films/<int:film_id>/scenes/add", methods=["POST"])
def add_scene(film_id):
    try:
        # Extract data from request
        scene_number = request.form.get("scene_number").strip()
        description = request.form.get("description", "").strip()
        start_date = request.form.get("start_date").strip()
        due_date = request.form.get("due_date").strip()

        # Insert into database
        conn = get_db()
        conn.execute("""
            INSERT INTO scenes (film_id, scene_number, description, start_date, due_date)
            VALUES (?, ?, ?, ?, ?)
        """, (film_id, scene_number, description, start_date, due_date))
        conn.commit()

        return jsonify({"success": True, "message": "Scene added successfully."})

    except Exception as e:
        print(f"âŒ Failed to add scene for film {film_id}: {e}")
        return jsonify({"error": f"Failed to add scene for film {film_id}"}), 500


@film_config_bp.route("/scenes/<int:scene_id>/shots/add", methods=["POST"])
def add_shot(scene_id):
    try:
        # Extract data from request
        shot_number = request.form.get("shot_number").strip()
        description = request.form.get("description", "").strip()
        start_date = request.form.get("start_date").strip()
        due_date = request.form.get("due_date").strip()

        # Insert into database
        conn = get_db()
        conn.execute("""
            INSERT INTO shots (scene_id, shot_number, description, start_date, due_date)
            VALUES (?, ?, ?, ?, ?)
        """, (scene_id, shot_number, description, start_date, due_date))
        conn.commit()

        shot_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Seed shot_step_assignments with each step's top node so this shot
        # never falls back to a mismatched default status in the dashboard.
        scene = conn.execute("SELECT film_id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
        film = conn.execute("SELECT step_id FROM films WHERE id = ?", (scene["film_id"],)).fetchone() if scene else None

        if film and film["step_id"]:
            excluded_step_ids = [row["step_id"] for row in conn.execute("""
                SELECT step_id FROM film_step_progress WHERE film_id = ?
            """, (scene["film_id"],)).fetchall()]

            steps = conn.execute("""
                SELECT st.id FROM steps st
                WHERE st.parent_id = ?
                AND st.id NOT IN ({})
                ORDER BY st.order_num ASC
            """.format(",".join("?" * len(excluded_step_ids))), [film["step_id"]] + excluded_step_ids).fetchall()

            for step in steps:
                top_node = conn.execute("""
                    SELECT name FROM nodes
                    WHERE step_id = ?
                    ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS FLOAT) ASC
                    LIMIT 1
                """, (step["id"],)).fetchone()

                conn.execute("""
                    INSERT INTO shot_step_assignments (shot_id, step_id, status, due_date)
                    VALUES (?, ?, ?, ?)
                """, (shot_id, step["id"], top_node["name"] if top_node else "Not Started", due_date or None))

            conn.commit()

        return jsonify({"success": True, "message": "Shot added successfully."})

    except Exception as e:
        print(f"âŒ Failed to add shot for scene {scene_id}: {e}")
        return jsonify({"error": f"Failed to add shot for scene {scene_id}"}), 500

@film_config_bp.route("/films/<int:film_id>/assets/add", methods=["POST"])
def add_assets_to_film(film_id):
    """
    Add all or selected assets for THIS film.
    It simply returns the film's assets (no duplication or inserts).
    """
    try:
        data = request.get_json() or {}
        add_all = data.get("add_all", False)
        selected_asset_ids = data.get("asset_ids", [])

        conn = get_db()

        # 🔹 Get all assets belonging to THIS film
        all_assets = conn.execute("""
            SELECT id, name, category, file_path
            FROM assets
            WHERE film_id = ?
            ORDER BY category, name
        """, (film_id,)).fetchall()

        if not all_assets:
            return jsonify({"error": f"No assets found for film {film_id}."}), 404

        # 🔹 Filter only chosen ones if user selected specific IDs
        if not add_all and selected_asset_ids:
            all_assets = [a for a in all_assets if a["id"] in selected_asset_ids]

        # Convert to dict list for JSON
        result = [dict(a) for a in all_assets]

        return jsonify({
            "success": True,
            "message": f"{len(result)} assets added to config view.",
            "assets": result
        })

    except Exception as e:
        print(f"❌ Failed to fetch assets for film {film_id}: {e}")
        return jsonify({"error": str(e)}), 500

# ----------------------------------------------------------------------------------------------------------------------
# REMOVING
# ----------------------------------------------------------------------------------------------------------------------

@film_config_bp.route("/scenes/<int:scene_id>/remove", methods=["POST"])
def remove_scene_from_config(scene_id):
    try:
        # Load the current config
        if not os.path.exists(CONFIG_PATH):
            return jsonify({"error": "No config file found."}), 404
        
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)

        # Remove the scene from the config
        for film_id, film in config.items():
            film["scenes"] = [s for s in film.get("scenes", []) if s["id"] != scene_id]

        # Save the updated config
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)

        return jsonify({"success": True, "message": "Scene removed from config."})

    except Exception as e:
        print(f"âŒ Failed to remove scene from config: {e}")
        return jsonify({"error": f"Failed to remove scene from config: {e}"}), 500

@film_config_bp.route("/films/remove/<int:film_id>", methods=["POST"])
def remove_film_from_config(film_id):
    try:
        # Load the current config
        if not os.path.exists(CONFIG_PATH):
            return jsonify({"error": "No config file found."}), 404
        
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)

        # Remove the film from the config
        if str(film_id) in config:
            del config[str(film_id)]
        else:
            return jsonify({"error": f"Film ID {film_id} not found in config."}), 404

        # Save the updated config
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)

        return jsonify({"success": True, "message": "Film removed from config."})

    except Exception as e:
        print(f"âŒ Failed to remove film from config: {e}")
        return jsonify({"error": f"Failed to remove film from config: {e}"}), 500

# ----------------------------------------------------------------------------------------------------------------------
# SAVING
# ----------------------------------------------------------------------------------------------------------------------

@film_config_bp.route("/api/save-draft", methods=["POST"])
def save_draft_only():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing config payload."}), 400

    try:
        for film_id, film_data in data.items():
            film_title = film_data.get("title")

            if not film_title:
                continue

            for scene_data in film_data.get("scenes", {}).values():
                for shot in scene_data.get("shots", []):
                    if not isinstance(shot, dict):
                        continue

                    assets = shot.get("assets", {})
                    resolved_assets = {}

                    for category, asset_list in assets.items():
                        if not isinstance(asset_list, list):
                            continue

                        # --- Normalize category ---
                        norm = category
                        cat_key = category.lower().replace(" ", "")
                        if cat_key in ("characterrigs", "charactersrigs", "character/rigs"):
                            norm = "Rigs"

                        resolved_assets.setdefault(norm, [])

                        for asset in asset_list:
                            # --- Extract name safely ---
                            if isinstance(asset, str):
                                name = asset.strip()
                            elif isinstance(asset, dict):
                                name = asset.get("name", "").strip()
                            else:
                                continue

                            if not name:
                                continue

                            # --- Resolve path SAFELY ---
                            try:
                                file_path = find_matching_asset_file(
                                    film_title,
                                    norm,
                                    name
                                )
                            except Exception as e:
                                print(
                                    f"⚠️ Asset resolve failed: "
                                    f"{film_title} | {norm} | {name} — {e}"
                                )
                                file_path = None

                            resolved_assets[norm].append({
                                "name": name,
                                "file_path": file_path
                            })

                    # 🔒 overwrite shot assets safely
                    shot["assets"] = resolved_assets

        with open(DRAFT_CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)

        return jsonify({
            "message": "Draft saved.",
            "draft_path": DRAFT_CONFIG_PATH
        })

    except Exception as e:
        print("❌ save_draft_only failed:", e)
        return jsonify({"error": str(e)}), 500


@film_config_bp.route("/api/save", methods=["POST"])
def save_film_config():
    print("🔥 /api/save HIT")

    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing config payload."}), 400

    try:
        for film_id, film_data in data.items():
            film_title = film_data["title"]
            for scene_data in film_data.get("scenes", {}).values():
                for shot in scene_data.get("shots", []):
                    if isinstance(shot, dict):
                        assets = shot.get("assets", {})
                        # --- Normalize categories so Character/Rigs → Rigs ---
                        db = get_db()

                        for category, asset_list in assets.items():

                            # ---- Normalize category before DB lookup ----
                            cat_key = category.lower().replace(" ", "")
                            if cat_key in ("characterrigs", "charactersrigs", "character/rigs"):
                                norm_category = "Rigs"
                            else:
                                norm_category = category

                            enriched = []

                            for asset in asset_list:
                                name = asset if isinstance(asset, str) else asset.get("name")

                                print("LOOKUP →", film_id, norm_category, name)
                                row = db.execute("""
                                    SELECT file_path
                                    FROM assets
                                    WHERE film_id = ?
                                    AND LOWER(TRIM(category)) = LOWER(TRIM(?))
                                    AND LOWER(TRIM(name)) = LOWER(TRIM(?))
                                """, (film_id, norm_category, name)).fetchone()

                                print("RESULT →", row)
                                file_path = row["file_path"] if row else None

                                enriched.append({
                                    "name": name,
                                    "file_path": file_path
                                })

                            assets[category] = enriched

        version = len([f for f in os.listdir(CONFIG_DIR) if f.startswith("film_config_v")]) + 1
        filename = f"film_config_v{version}.json"
        path = os.path.join(CONFIG_DIR, filename)

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        with open(DRAFT_CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)

        return jsonify({
            "message": "Draft and versioned config saved.",
            "versioned_path": path,
            "draft_path": DRAFT_CONFIG_PATH
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@film_config_bp.route("/api/configs", methods=["GET"])
def list_saved_configs():
    try:
        all_files = sorted([
            f for f in os.listdir(CONFIG_DIR)
            if f.endswith(".json") and (
                f.startswith("film_config_v") or f == "_draft_film_config.json"
            )
        ])
        logging.debug(f"ðŸ“‚ Available config files: {all_files}")
        return jsonify({"configs": all_files})
    except Exception as e:
        logging.error(f"âŒ Error listing configs: {e}")
        return jsonify({"error": str(e)}), 500


@film_config_bp.route("/api/load/<filename>", methods=["GET"])
def load_saved_config(filename):
    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found."}), 404

    with open(path) as f:
        return jsonify(json.load(f))

@film_config_bp.route("/api/save-json", methods=["POST"])
def save_final_json():

    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing config payload."}), 400

    try:
        db = get_db()

        # 🔥 Rebuild asset file paths from DB
        for film_id, film_data in data.items():

            for scene_data in film_data.get("scenes", {}).values():
                for shot in scene_data.get("shots", []):

                    if not isinstance(shot, dict):
                        continue

                    rebuilt_assets = {}

                    for category, asset_list in shot.get("assets", {}).items():

                        rebuilt_assets.setdefault(category, [])

                        # Normalize to match DB
                        cat_key = category.lower().replace(" ", "")
                        if cat_key in ("characterrigs", "charactersrigs", "character/rigs"):
                            norm_category = "Character/Rigs"
                        else:
                            norm_category = category

                        for asset in asset_list:

                            name = asset["name"] if isinstance(asset, dict) else asset

                            row = db.execute("""
                                SELECT file_path
                                FROM assets
                                WHERE film_id = ?
                                  AND LOWER(TRIM(category)) = LOWER(TRIM(?))
                                  AND LOWER(TRIM(name)) = LOWER(TRIM(?))
                            """, (film_id, norm_category, name)).fetchone()

                            file_path = row["file_path"] if row else None

                            rebuilt_assets[category].append({
                                "name": name,
                                "file_path": file_path
                            })

                    shot["assets"] = rebuilt_assets

        # 🔥 Now write the enriched JSON
        output_dir = r"C:\Cincy\Configs"
        os.makedirs(output_dir, exist_ok=True)

        output_path = os.path.join(output_dir, "film_config_v1.json")
        capstone_output_path = os.path.join(output_dir, "capstone_config_v1.json")

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

        # Same resolved film/scene/shot/asset structure, written a second
        # time under the name the Phase 5 capstone pipeline (scene/shot
        # Layout, Animation, Lighting) reads -- one save action, two
        # deployed files, so there's a single source of truth instead of a
        # second editor that could drift out of sync with this one.
        with open(capstone_output_path, "w") as f:
            json.dump(data, f, indent=2)

        return jsonify({
            "message": "Final JSON saved.",
            "json_path": output_path,
            "capstone_json_path": capstone_output_path
        })

    except Exception as e:
        print("❌ Failed to save final JSON:", str(e))
        return jsonify({"error": str(e)}), 500



@film_config_bp.route("/films/config/api/publish/<filename>", methods=["POST"])
def publish_config(filename):
    src = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(src):
        return jsonify({"error": "File not found."}), 404

    with open(src, "r") as f:
        data = f.read()

    with open(FINAL_CONFIG_PATH, "w") as f:
        f.write(data)

    return jsonify({"message": "Published to final config.", "path": FINAL_CONFIG_PATH})

@film_config_bp.route("/films/config/api/test-asset", methods=["GET"])
def test_asset_lookup():
    film = request.args.get("film", "Vacation")
    category = request.args.get("category", "Rigs")
    name = request.args.get("name", "Alien 1")

    path = find_matching_asset_file(film, category, name)

    return jsonify({
        "film": film,
        "category": category,
        "asset": name,
        "resolved_path": path
    })


