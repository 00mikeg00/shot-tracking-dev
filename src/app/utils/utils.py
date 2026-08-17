import json
import os
import re
from functools import wraps
from flask import session, redirect, url_for, flash, jsonify, render_template
from app.models.classes import get_class_by_id
from app.database.db import get_db

def flash_message(message: str, category: str = 'info') -> None:
    """Flash a message with a specified category."""
    flash(message, category)

#  Role Required Decorator
def role_required(sections, allowed_roles):
    if isinstance(sections, str):
        sections = [sections]

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            if 'user_id' not in session:
                return render_template('error_popup.html', message="Unauthorized: Please log in", level="error"), 401

            user_roles = session.get('roles', {})

            if isinstance(user_roles, list):
                if any(role.lower() in [r.lower() for r in allowed_roles] for role in user_roles):
                    return view_func(*args, **kwargs)

            if isinstance(user_roles, dict):
                for section in sections:
                    user_role = user_roles.get(section)
                    if user_role and user_role.lower() in [r.lower() for r in allowed_roles]:
                        return view_func(*args, **kwargs)

            print(f"ACCESS DENIED for {session.get('username')} in {sections} roles: {user_roles}")
            return render_template('error_popup.html', message="Forbidden: You don't have permission", level="error"), 403

        return wrapped_view
    return decorator


#  Class Existence Check
def check_class_exists(class_id: int):
    """Ensure the class exists in the database."""
    selected_class = get_class_by_id(class_id)
    if not selected_class:
        flash("Class not found.", "danger")
        return None
    return selected_class

#  Class Validation
def validate_class_data(data: dict) -> bool:
    """Validate class input fields before inserting into DB."""
    required_fields = ["year", "semester", "code", "class_number", "class_name"]
    return all(field in data and data[field] for field in required_fields)

#  User/Group Validation for Linking
def validate_user_and_group_existence(user_id: int, group_id: int) -> None:
    """
    Raise ValueError if user or group ID does not exist in DB.
    """
    conn = get_db()
    user_exists = conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (user_id,)).fetchone()[0] > 0
    group_exists = conn.execute("SELECT COUNT(*) FROM groups WHERE id = ?", (group_id,)).fetchone()[0] > 0

    if not user_exists:
        raise ValueError(f"User with ID {user_id} does not exist.")
    if not group_exists:
        raise ValueError(f"Group with ID {group_id} does not exist.")
    
def get_classes_data():
    db = get_db()
    cursor = db.cursor()

    # Join class names with assignment configs
    cursor.execute("""
        SELECT c.class_name, a.assignment_name, a.filename, a.camera, a.rigs
        FROM classes c
        JOIN assignment_config_presets a ON c.id = a.class_id
    """)

    result = {}
    for row in cursor.fetchall():
        class_name, a_name, filename, camera, rigs_json = row

        if class_name not in result:
            result[class_name] = {}

        result[class_name][a_name] = {
            "filename": filename or "",
            "camera": bool(camera),
            "rigs": json.loads(rigs_json or "[]")
        }

    return result

def flash_and_redirect(message: str, category: str, endpoint: str, **kwargs):
    """Flash a message and redirect to a given endpoint."""
    flash(message, category)
    return redirect(url_for(endpoint, **kwargs))

#---------------------------------------------------------------------------------
# ASSETS
#---------------------------------------------------------------------------------

ASSET_ROOT = r"\\GAAAP1PRD01W\Films"

# Single source of truth for category -> on-disk folder name, shared by
# find_matching_asset_file() (lookup) and ensure_asset_folder() (creation)
# so a newly created asset's folder is always the one later lookups will
# actually search.
CATEGORY_FOLDER_MAP = {
    "Sets": "Sets",
    "Character/Rigs": "Rigs",
    "Rigs": "Rigs",
    "Props - 3D": "Props_-_3D",
    "Props - 2D": "Props_-_2D",
    "Light Rigs": "LightRigs",
    "BGs": "BGs"
}

# Step short_codes (see step_codes table) that don't gate each other's
# approval within a category, unlike the normal strict order_num chain --
# e.g. Character/Rigs' Texture-Surface and Rigging can both be worked on
# independently once Modeling is approved. They still can't be open in
# Maya at the same time (step_checkouts enforces that separately), since
# both share one continuous version lineage on disk. Consulted by
# resolve_current_step() in both dashboard_routes.py and deploy/Assets.py
# -- keep those two in agreement with this map.
MUTUALLY_EXCLUSIVE_STEP_GROUPS = {
    "Character/Rigs": [{"TEX", "RIG"}],
}


def get_asset_category_dir(film_title, category):
    """Returns Assets/<Category>/ for this film, or None for an unmapped category."""
    folder = CATEGORY_FOLDER_MAP.get(category)
    if not folder:
        return None
    return os.path.join(ASSET_ROOT, film_title, "Assets", folder)


def ensure_asset_folder(film_title, category, asset_name):
    """
    Creates Assets/<Category>/<Asset Name>/ on disk if it doesn't already
    exist, so a newly added asset has somewhere to save files into right
    away instead of only getting a folder the next time someone regenerates
    folders from the film config. Returns the folder path, or None if the
    category isn't mapped or asset_name is empty.
    """
    if not asset_name:
        return None
    asset_name = asset_name.strip()

    category_dir = get_asset_category_dir(film_title, category)
    if not category_dir:
        return None

    asset_dir = os.path.join(category_dir, asset_name)
    os.makedirs(asset_dir, exist_ok=True)
    return asset_dir


def find_matching_asset_file(film_title, category, asset_name):
    """
    Find highest version of:
    NAME[_anything]_v###.mb
    inside:
    Assets/<Category>/<Asset Name>/

    Proxy files (_PROXY_-tagged) are excluded -- Proxy is a separate,
    independent lineage from Modeling/Texture-Surface/Rigging (see
    Assets.py's find_latest_asset_version(), which mirrors this same
    exclusion on the Maya side). Without it, a brand-new asset with only a
    Proxy file would get its official production file_path resolved to
    the proxy instead of staying unset until real production work exists.
    """

    if not asset_name:
        return None

    asset_name = asset_name.strip()

    category_dir = get_asset_category_dir(film_title, category)
    if not category_dir:
        return None

    if not os.path.isdir(category_dir):
        return None

    # 🔑 ASSET-NAME SUBFOLDER (THIS WAS MISSING)
    asset_dir = os.path.join(category_dir, asset_name)

    if not os.path.isdir(asset_dir):
        return None

    # Allow space / underscore variations
    safe_name = re.escape(asset_name).replace(r"\ ", r"[ _]")

    pattern = re.compile(
        rf"^{safe_name}.*?_v(\d+)\.(ma|mb)$",
        re.IGNORECASE
    )

    highest_version = -1
    best_file = None

    for filename in os.listdir(asset_dir):
        if "_PROXY_" in filename.upper():
            continue
        match = pattern.match(filename)
        if not match:
            continue

        version = int(match.group(1))
        if version > highest_version:
            highest_version = version
            best_file = filename

    if not best_file:
        return None

    return os.path.join(asset_dir, best_file)







