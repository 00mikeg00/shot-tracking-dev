import os
import re
import sqlite3
from collections import defaultdict
from flask import Flask, jsonify
from flask import current_app as app
from app.database.db import get_db


CLASSES_BASE = os.getenv("CLASSES_PATH", r"C:/Classes")
FILMS_BASE = os.getenv("FILMS_PATH", r"\\GAAAP1PRD01W\Films")



# DATABASE CONFIG - UPDATE WITH YOUR DB PATH
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATABASE_PATH = os.getenv(
    "DATABASE",
    os.path.join(BASE_DIR, "database", "app.db")
)

print("🔍 REVIEW DB PATH:", DATABASE_PATH)
print("🔍 EXISTS:", os.path.exists(DATABASE_PATH))

# [OK] Function to connect to the database
def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def extract_assignment_id(assignment_name, class_id):
    """ Get assignment_id from assignment name & class_id — normalizes spaces for camp filenames """
    conn = get_db_connection()
    cursor = conn.cursor()

    # First try exact match
    cursor.execute("""
        SELECT id, name FROM assignments WHERE class_id = ?
    """, (class_id,))

    rows = cursor.fetchall()
    conn.close()

    # Normalize: remove spaces, lowercase for comparison
    normalized_input = assignment_name.replace(" ", "").lower()

    for row in rows:
        if row["name"].replace(" ", "").lower() == normalized_input:
            return row["id"]

    return None

def extract_users_id(user_name):
    """ Get users_id from user name — normalizes spaces for camp filenames """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM users")
    rows = cursor.fetchall()
    conn.close()

    normalized_input = user_name.replace(" ", "").lower()

    for row in rows:
        if row["name"].replace(" ", "").lower() == normalized_input:
            return row["id"]

    return None

def get_individual_assignment_id(assignment_id, users_id):
    """ [OK] Get individual_assignment_id from assignment_id & users_id """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id FROM individual_assignments WHERE assignment_id = ? AND users_id = ?
    """, (assignment_id, users_id))

    result = cursor.fetchone()
    conn.close()
    return result["id"] if result else None

def get_class_id(class_name):
    """
    Get class_id from class_name (normalized match). Excludes archived
    classes -- without this, an archived duplicate with the same name as
    an active class (e.g. two "Intermediate Animation" rows, one archived
    and one not) can still win this match depending on row order, silently
    resolving every submitted file in that class to the WRONG class_id/
    assignment_id and breaking individual_assignments lookups for
    students who are only enrolled in the active one.
    """

    # Normalize filesystem name
    normalized = class_name.lower()
    normalized = normalized.replace("_", " ")
    normalized = normalized.replace("&", "and")
    normalized = re.sub(r"\s+", " ", normalized).strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, class_name FROM classes WHERE COALESCE(archived, 0) = 0
    """)

    for row in cursor.fetchall():
        db_name = row["class_name"].lower()
        db_name = db_name.replace("&", "and")
        db_name = re.sub(r"\s+", " ", db_name).strip()

        if db_name == normalized:
            conn.close()
            return row["id"]

    conn.close()
    return None


def extract_user_name(file_name):
    """ [OK] Extracts the user name correctly from filenames like assignment_user name_v#.webm """
    pattern = r'_(.*?)_v\d'  # [OK] Extracts text between first `_` and `_v#`
    match = re.search(pattern, file_name)
    
    if match:
        return match.group(1)  # [OK] Return extracted user name
    return None  #  No match found

def get_all_assignment_files():
    files_to_review = []  # Unreviewed files
    all_files = {}        # Grouped by class

    if not os.path.exists(CLASSES_BASE):
        print(f"ERROR: Classes directory not found: {CLASSES_BASE}")
        return []

    for semester_folder in os.listdir(CLASSES_BASE):
        semester_path = os.path.join(CLASSES_BASE, semester_folder)
        if not os.path.isdir(semester_path):
            continue

        for class_name in os.listdir(semester_path):
            class_path = os.path.join(semester_path, class_name)
            assignments_path = os.path.join(class_path, "Assignments")

            if not os.path.exists(assignments_path):
                continue

            class_id = get_class_id(class_name)
            if not class_id:
                print(f"ERROR: Class not found in database: {class_name}")
                continue

            display_key = f"{semester_folder} - {class_name}"
            all_files[display_key] = []

            for file in os.listdir(assignments_path):
                if file.endswith(".webm") or file.endswith(".png"):
                    file_path = os.path.join(assignments_path, file)

                    # Assignment name (can have spaces, #, numbers, letters, dashes) before first underscore
                    match = re.match(
                        r"^(.+?)_([^_]+(?: [^_]+)*)(?:_([A-Z]{1,2}))?_v(\d+)(_R)?\.(webm|png)$",
                        file
                    )


                    if not match:
                        print(f"Regex didn't match for: {file}")
                        continue

                    try:
                        assignment_name, user_name, step_code, version, is_reviewed, ext = match.groups()
                    except Exception as e:
                        print(f"❌ Error unpacking regex groups for {file}: {e}")
                        continue



                    assignment_id = extract_assignment_id(assignment_name, class_id)
                    users_id = extract_users_id(user_name)

                    if not assignment_id:
                        print(f"Assignment not found: {assignment_name} in {class_name}")
                        continue
                    if not users_id:
                        print(f"User not found: {user_name}")
                        continue

                    individual_assignment_id = get_individual_assignment_id(assignment_id, users_id)

                    file_entry = {
                        "class_id": class_id,
                        "class_name": class_name,
                        "assignment_id": assignment_id,
                        "individual_assignment_id": individual_assignment_id,
                        "file_name": file,
                        "file_path": file_path.replace("\\", "/"),
                        "is_reviewed": bool(is_reviewed)
                    }

                    all_files[display_key].append(file_entry)

                    # Skip originals if an _R version exists on disk
                    if not file_entry["is_reviewed"]:
                        reviewed_name = file_entry["file_name"].replace(".webm", "_R.webm")
                        reviewed_path = os.path.join(assignments_path, reviewed_name)
                        if os.path.exists(reviewed_path):
                            print(f"⚠️ Skipping original because reviewed exists: {file_entry['file_name']}")
                            continue
                        files_to_review.append(file_entry)

                    # Always keep reviewed files in all_files, but not in files_to_review
                    all_files[display_key].append(file_entry)


    return {"files_to_review": files_to_review, "all_files": all_files}



assignment_files = None

def get_assignment_files_lazy():
    global assignment_files
    if assignment_files is None:
        assignment_files = get_all_assignment_files()
    return assignment_files



def get_assignments_for_review():
    files = get_all_assignment_files()

    return files["files_to_review"]

def get_all_film_files():
    all_files = {}  # { film_name: [file_entry, ...] }

    if not os.path.exists(FILMS_BASE):
        print(f"ERROR: Films directory not found: {FILMS_BASE}")
        return {}

    conn = get_db_connection()
    cursor = conn.cursor()

    for film_name in os.listdir(FILMS_BASE):
        film_path = os.path.join(FILMS_BASE, film_name)
        if not os.path.isdir(film_path):
            continue

        thumbnails_path = os.path.join(film_path, "Thumbnails")
        if not os.path.exists(thumbnails_path):
            continue

        film_files = []

        for fname in os.listdir(thumbnails_path):
            if not re.search(r"(_THUMB|_SB)_v\d+(?:_R)?\.(mov|mp4|webm|json)$", fname, re.IGNORECASE):
                continue

            file_path = os.path.join(thumbnails_path, fname).replace("\\", "/")
            normalized_name = fname.lower().replace("_", " ")

            # Extract scene_number from file
            scene_match = re.search(r"_(\d+)_thumb", fname, re.IGNORECASE)
            scene_number = scene_match.group(1) if scene_match else None

            scene_id = None
            if scene_number:
                cursor.execute("""
                    SELECT s.id
                    FROM scenes s
                    JOIN films f ON f.id = s.film_id
                    WHERE LOWER(REPLACE(?, '_', ' ')) LIKE '%' || LOWER(REPLACE(f.name, '_', ' ')) || '%'
                      AND ? LIKE '%' || s.scene_number || '%'
                    LIMIT 1
                """, (fname, scene_number))
                row = cursor.fetchone()
                if row:
                    scene_id = row["id"]

            film_files.append({
                "file_name": fname,
                "file_path": file_path,
                "scene_id": scene_id
            })

        if film_files:
            all_files[film_name] = film_files

    conn.close()
    return all_files



def get_films_for_review(cursor):
    reviewed = defaultdict(lambda: defaultdict(list))
    to_review = defaultdict(lambda: defaultdict(list))

    base_dir = os.getenv("FILMS_ROOT", r"\\GAAAP1PRD01W\Films")

    for root, _, files in os.walk(base_dir):

        # --------------------------------------------------
        # Detect THUMB / SB scene folders (010_THUMB, 010_SB)
        # --------------------------------------------------
        folder_match = re.search(r"[\\/](\d{3})_(THUMB|SB)[\\/]", root, re.IGNORECASE)
        folder_scene = folder_match.group(1) if folder_match else None

        # --------------------------------------------------
        # Detect Reviewed Thumbnails folder
        # --------------------------------------------------
        is_reviewed_thumb_dir = re.search(r"[\\/]Thumbnails[\\/]Reviewed", root, re.IGNORECASE)

        for filename in files:
            if not filename.lower().endswith((".webm", ".mov", ".mp4", ".json")):
                continue

            full_path = os.path.join(root, filename)
            filename_lower = filename.lower()

            film_part = scene_number = shot_number = None

            # --------------------------------------------------
            # SHOT FILES
            # Film_010_020_STEP_USER_v2[_R].ext
            # --------------------------------------------------
            shot_match = re.search(
                r"^([A-Za-z0-9 ]+)_(\d{3})_(\d{3})_[A-Z0-9_]+_.*_v\d+(?:_R)?\.(webm|mov|mp4|json)$",
                filename,
                re.IGNORECASE
            )

            if shot_match:
                film_part = shot_match.group(1)
                scene_number = shot_match.group(2)
                shot_number = shot_match.group(3)

            # --------------------------------------------------
            # THUMB / SB IN SCENE FOLDERS
            # \Thumbnails\010_THUMB\file.webm
            # \Thumbnails\010_SB\file.webm
            # --------------------------------------------------
            elif folder_scene:
                film_part = os.path.basename(os.path.dirname(os.path.dirname(root)))
                scene_number = folder_scene
                shot_number = "000"

            # --------------------------------------------------
            # REVIEWED THUMBNAILS
            # \Thumbnails\Reviewed\Film_010_THUMB_v1_R.webm
            # --------------------------------------------------
            elif is_reviewed_thumb_dir:
                m = re.search(r"^([A-Za-z0-9 ]+)_(\d{3})_", filename)
                if not m:
                    continue

                film_part = m.group(1)
                scene_number = m.group(2)
                shot_number = "000"

            else:
                continue

            # --------------------------------------------------
            # DB lookup
            # --------------------------------------------------
            row = None
            try:
                cursor.execute("""
                    SELECT s.id, fi.name
                    FROM scenes s
                    JOIN films fi ON fi.id = s.film_id
                    WHERE LOWER(REPLACE(?, '_', ' ')) LIKE '%' || LOWER(REPLACE(fi.name, '_', ' ')) || '%'
                    AND s.scene_number = ?
                """, (filename_lower, scene_number))
                row = cursor.fetchone()
            except Exception:
                continue

            if row:
                scene_id = row[0]
                film_title = row[1]
            else:
                cursor.execute("SELECT name FROM films")
                films = [r["name"] for r in cursor.fetchall()]
                norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
                film_title = next((f for f in films if norm(f) == norm(film_part)), film_part)
                scene_id = None

            # 🔒 Normalize film title key (prevents duplicate folders)
            film_title = film_title.strip()


            file_obj = {
                "file_name": filename,
                "file_path": full_path.replace("\\", "/"),
                "scene_id": scene_id,
                "scene_number": scene_number,
                "shot_number": shot_number,
            }

            is_reviewed = "_r." in filename_lower or is_reviewed_thumb_dir

            if is_reviewed:
                reviewed[film_title][scene_number].append(file_obj)
            else:
                to_review[film_title][scene_number].append(file_obj)

    return {
        "reviewed": {film: dict(scenes) for film, scenes in reviewed.items()},
        "to_review": {film: dict(scenes) for film, scenes in to_review.items()},
    }





