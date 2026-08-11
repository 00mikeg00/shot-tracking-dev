from app.database.db import get_db


# ----------------------------------------------------------------------------------------------------------------------
# OVERALL MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def get_all_semesters():
    conn = get_db()
    return conn.execute("SELECT * FROM semesters ORDER BY year DESC, term DESC").fetchall()

def get_users_by_group_name(group_name):
    query = """
        SELECT u.id, u.name
        FROM users u
        JOIN user_groups ug ON u.id = ug.user_id
        JOIN groups g ON ug.group_id = g.id
        WHERE g.name = ?
        ORDER BY u.name
    """
    conn = get_db()
    return conn.execute(query, (group_name,)).fetchall()

# ----------------------------------------------------------------------------------------------------------------------
# FILMS MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def get_all_films():
    query = """
    SELECT 
        f.id, f.name, f.description, f.created_at,
        f.step_id,
        s.term || ' ' || s.year AS semester,
        d.name AS director_name,
        u.name AS upm_name
    FROM films f
    LEFT JOIN semesters s ON f.semester_id = s.id
    LEFT JOIN users d ON f.director_id = d.id
    LEFT JOIN users u ON f.upm_id = u.id
    ORDER BY f.name ASC
    """
    conn = get_db()
    results = conn.execute(query).fetchall()
    return [dict(row) for row in results]

def get_film_by_id(film_id):
    """Fetch a specific film by its ID."""
    query = """
    SELECT 
        f.id, f.name, f.description,
        f.semester_id, f.director_id, f.upm_id,
        s.term || ' ' || s.year AS semester,
        d.name AS director_name,
        u.name AS upm_name
    FROM films f
    LEFT JOIN semesters s ON f.semester_id = s.id
    LEFT JOIN users d ON f.director_id = d.id
    LEFT JOIN users u ON f.upm_id = u.id
    WHERE f.id = ?
    """
    conn = get_db()
    return conn.execute(query, (film_id,)).fetchone()

def add_film(data):
    conn = get_db()
    cursor = conn.execute(
        """
        INSERT INTO films (name, description, semester_id, director_id, upm_id, step_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"],
            data.get("description", ""),
            data.get("semester_id"),
            data.get("director_id"),
            data.get("upm_id"),
            data.get("step_id")
        )
    )
    conn.commit()
    
    # [OK] Return the generated film ID
    return cursor.lastrowid

def update_film(film_id, data):
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE films
            SET name = ?, description = ?, semester_id = ?, director_id = ?, upm_id = ?
            WHERE id = ?
            """,
            (
                data["name"],
                data.get("description", ""),
                data.get("semester_id"),
                data.get("director_id"),
                data.get("upm_id"),
                film_id
            )
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error updating film {film_id}: {e}")
        raise e

def delete_film(film_id):
    db = get_db()
    try:
        # Remove new step tables first
        db.execute("DELETE FROM preproduction_steps WHERE film_id = ?", (film_id,))
        db.execute("DELETE FROM production_steps WHERE film_id = ?", (film_id,))

        # Remove shot-related data
        db.execute("""
            DELETE FROM shot_step_assignments
            WHERE shot_id IN (
                SELECT id FROM shots WHERE scene_id IN (
                    SELECT id FROM scenes WHERE film_id = ?
                )
            )
        """, (film_id,))
        db.execute("""
            DELETE FROM shots
            WHERE scene_id IN (
                SELECT id FROM scenes WHERE film_id = ?
            )
        """, (film_id,))

        # Add before deleting scenes
        db.execute("""
            DELETE FROM scene_progress_steps
            WHERE scene_id IN (
                SELECT id FROM scenes WHERE film_id = ?
            )
        """, (film_id,))

        db.execute("""
            DELETE FROM scene_assets
            WHERE scene_id IN (
                SELECT id FROM scenes WHERE film_id = ?
            )
        """, (film_id,))

        # Remove scenes
        db.execute("DELETE FROM scenes WHERE film_id = ?", (film_id,))

        # Remove film_step_progress
        db.execute("DELETE FROM film_step_progress WHERE film_id = ?", (film_id,))

        # Remove asset-related data
        db.execute("""
            DELETE FROM asset_step_assignments
            WHERE asset_id IN (
                SELECT id FROM assets WHERE film_id = ?
            )
        """, (film_id,))
        db.execute("DELETE FROM assets WHERE film_id = ?", (film_id,))

        # Remove film crew
        db.execute("DELETE FROM film_crew WHERE film_id = ?", (film_id,))

        # Finally, remove the film
        db.execute("DELETE FROM films WHERE id = ?", (film_id,))

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Error deleting film {film_id}: {e}")
        raise e



# ----------------------------------------------------------------------------------------------------------------------
# SCENES MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def get_scenes_for_film(film_id):
    conn = get_db()
    query = """
        SELECT 
            id, scene_number, description, created_at
        FROM scenes
        WHERE film_id = ?
        ORDER BY scene_number COLLATE NOCASE
    """
    return conn.execute(query, (film_id,)).fetchall()

def has_crossflows(step_id: int) -> bool:
    """
    Returns True if the given step_id has any crossflow links (to_flow_id not null).
    """
    conn = get_db()
    cursor = conn.execute("""
        SELECT 1 FROM links
        WHERE step_id = ? AND to_flow_id IS NOT NULL
        LIMIT 1
    """, (step_id,))
    return cursor.fetchone() is not None

def add_scene(film_id, data):
    conn = get_db()
    cursor = conn.cursor()

    # [OK] Safely coerce workflow_id, fallback to None
    try:
        workflow_id = int(data.get("workflow_id"))
    except (TypeError, ValueError):
        raise ValueError(f"âŒ Invalid workflow_id: {data.get('workflow_id')}")

    cursor.execute("""
        INSERT INTO scenes (film_id, scene_number, description, start_date, due_date, workflow_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        film_id,
        data["scene_number"],
        data.get("description", ""),
        data.get("start_date", ""),
        data.get("due_date", ""),
        workflow_id
    ))

    scene_id = cursor.lastrowid

    for raw_step_id in data.get("step_ids", []):
        try:
            step_id = int(raw_step_id)
        except (TypeError, ValueError):
            continue

        top_node = cursor.execute("""
            SELECT name FROM nodes
            WHERE step_id = ?
            ORDER BY CAST(substr(position, instr(position, ' ') + 1) AS INTEGER)
            LIMIT 1
        """, (step_id,)).fetchone()

        status = top_node["name"] if top_node else "Not Started"

    conn.commit()
    return scene_id

# ----------------------------------------------------------------------------------------------------------------------
# WORKFLOWS MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def is_preproduction_complete_for_film(film_id):
    scenes = get_scenes_for_film(film_id)
    for scene in scenes:
        statuses = get_scene_statuses(scene["id"])
        for s in statuses:
            name = s["step_name"].lower()
            if name in ("story", "script", "story and script") and s["status"].lower() != "approved":
                return False
    return True

def get_prepro_status(film_id):
    scenes = get_scenes_for_film(film_id)
    for scene in scenes:
        for s in get_scene_statuses(scene["id"]):
            if s["step_name"].lower() in ("story", "script", "story and script"):
                return {"done": s["status"].lower() == "approved", "step": s, "scene_id": scene["id"]}
    return {"done": True, "step": None, "scene_id": None}

def get_all_workflows_flat():
    db = get_db()
    return db.execute("""
        SELECT id, name
        FROM steps
        WHERE parent_id IS NULL
        ORDER BY name
    """).fetchall()

def get_all_steps():
    query = "SELECT id, name, parent_id FROM steps"
    conn = get_db()
    return conn.execute(query).fetchall()

def get_steps_for_scene(scene_id):
    query = """
        SELECT s.id, s.name
        FROM scene_progress_steps sp
        JOIN steps s ON sp.step_id = s.id
        WHERE sp.scene_id = ?
        ORDER BY s.name
    """
    conn = get_db()
    return conn.execute(query, (scene_id,)).fetchall()

def get_scene_step_status(scene_id, step_id):
    query = """
        SELECT status
        FROM scene_progress_steps
        WHERE scene_id = ? AND step_id = ?
    """
    conn = get_db()
    result = conn.execute(query, (scene_id, step_id)).fetchone()
    return result["status"] if result else "Not Started"

def get_scene_statuses(scene_id):
    conn = get_db()
    return conn.execute("""
        SELECT s.id as step_id, s.name as step_name, sp.status
        FROM scene_progress_steps sp
        JOIN steps s ON sp.step_id = s.id
        WHERE sp.scene_id = ?
    """, (scene_id,)).fetchall()

def add_scene_step(scene_id, step_id):
    query = "INSERT INTO scene_progress_steps (scene_id, step_id) VALUES (?, ?)"
    conn = get_db()
    conn.execute(query, (scene_id, step_id))
    conn.commit()

def get_recursive_crossflows(db, parent_node_id, visited=None):
    if visited is None:
        visited = set()
    if parent_node_id in visited:
        return []

    visited.add(parent_node_id)

    results = []
    crossflows = db.execute("""
        SELECT l.to_flow_id, l.child_node_id, n.name, n.color
        FROM links l
        JOIN nodes n ON l.child_node_id = n.id
        WHERE l.parent_node_id = ?
    """, (parent_node_id,)).fetchall()

    for flow in crossflows:
        results.append(flow)
        results.extend(get_recursive_crossflows(db, flow["child_node_id"], visited))

    return results

# ----------------------------------------------------------------------------------------------------------------------
# ASSETS MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def get_all_assets():
    conn = get_db()
    query = '''
    SELECT 
        a.id, a.name, a.due_date, a.workflow_id,
        w.name AS workflow_name
    FROM assets a
    LEFT JOIN steps w ON a.workflow_id = w.id
    ORDER BY a.name ASC
    '''
    results = conn.execute(query).fetchall()
    return [dict(row) for row in results]

def get_asset_by_id(asset_id):
    conn = get_db()
    query = '''
    SELECT 
        a.id, a.name, a.due_date, a.workflow_id,
        w.name AS workflow_name
    FROM assets a
    LEFT JOIN steps w ON a.workflow_id = w.id
    WHERE a.id = ?
    '''
    return conn.execute(query, (asset_id,)).fetchone()

def add_asset(data):
    conn = get_db()
    cursor = conn.execute(
        '''
        INSERT INTO assets (name, due_date, workflow_id)
        VALUES (?, ?, ?)
        ''',
        (data['name'], data['due_date'], data['workflow_id'])
    )
    conn.commit()
    return cursor.lastrowid

def update_asset(asset_id, data):
    conn = get_db()
    conn.execute(
        '''
        UPDATE assets
        SET name = ?, due_date = ?, workflow_id = ?
        WHERE id = ?
        ''',
        (data['name'], data['due_date'], data['workflow_id'], asset_id)
    )
    conn.commit()

def delete_asset(asset_id):
    conn = get_db()
    conn.execute('DELETE FROM assets WHERE id = ?', (asset_id,))
    conn.commit()

def get_asset_status_summary(asset_id):
    conn = get_db()
    query = '''
    SELECT s.name AS label, COUNT(ssa.id) AS value, n.color AS color
    FROM asset_step_assignments ssa
    JOIN steps s ON ssa.step_id = s.id
    LEFT JOIN nodes n ON n.step_id = s.id AND n.name = ssa.status
    WHERE ssa.asset_id = ?
    GROUP BY s.name, n.color
    ORDER BY s.name
    '''
    return conn.execute(query, (asset_id,)).fetchall()

# ----------------------------------------------------------------------------------------------------------------------
# TIMELINE MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------


def seed_preproduction_steps(film_id):
    """Create default preproduction steps for a new film."""
    steps = [
        "Treatment",
        "Outline",
        "Script_Rough",
        "Script_Pass",
        "Locked_Script",
        "Voice_Record",
    ]

    conn = get_db()
    cursor = conn.cursor()

    for step in steps:
        cursor.execute("""
            INSERT INTO preproduction_steps (film_id, step_name, status)
            VALUES (?, ?, ?)
        """, (film_id, step, "Not Started"))

    conn.commit()
    conn.close()