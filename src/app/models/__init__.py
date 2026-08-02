import sqlite3
from flask import g, current_app
from app.config import DATABASE
from werkzeug.security import generate_password_hash, check_password_hash
from app.database.db import get_db, query_db, modify_db
from app.models.classes import get_class_by_id
from .films import *


def hash_password(password):
    """Hash a password for secure storage."""
    return generate_password_hash(password)

def get_user_by_login_name(username):
    """Fetch a user by their login username."""
    conn = get_db()
    query = "SELECT * FROM users WHERE login_name = ?"
    user = conn.execute(query, (username,)).fetchone()
    return user if user else None

def get_user_by_email(email):
    """Fetch a user from the database by email."""
    conn = get_db()
    query = "SELECT * FROM users WHERE email = ?"
    user = conn.execute(query, (email,)).fetchone()
    return user

def update_user_password(user_id, new_password_hash):
    """Update the user's password using their user_id."""
    conn = get_db()
    query = "UPDATE users SET password_hash = ? WHERE id = ?"
    conn.execute(query, (new_password_hash, user_id))
    conn.commit()
    
# ----------------------------------------------------------------------------------------------------------------------
# USER MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def query_users(filters=None, limit=None, offset=None):
    conn = get_db()
    cursor = conn.cursor()

    query = """
    SELECT 
        users.id, 
        users.name, 
        users.email, 
        users.login_name,
        GROUP_CONCAT(groups.name, ', ') AS groups
    FROM users
    LEFT JOIN user_groups ON users.id = user_groups.user_id
    LEFT JOIN groups ON user_groups.group_id = groups.id
    WHERE users.archived = 0
    """
    params = []

    if filters:
        filter_clauses = []
        if 'search' in filters:
            filter_clauses.append("(users.name LIKE ? OR users.email LIKE ?)")
            params.extend([f"%{filters['search']}%"] * 2)
        if 'id' in filters:
            filter_clauses.append("users.id = ?")
            params.append(filters['id'])
        if filter_clauses:
            query += " AND " + " AND ".join(filter_clauses)

    query += """
    GROUP BY users.id
    ORDER BY users.name
    """
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    if offset:
        query += " OFFSET ?"
        params.append(offset)

    cursor.execute(query, params)
    results = cursor.fetchall()

    return results

def get_all_groups():
    """Fetch all user groups from the database."""
    conn = get_db()
    try:
        groups = conn.execute("SELECT id, name, section FROM groups").fetchall()
        return [{'id': g['id'], 'name': g['name'], 'section': g['section']} for g in groups]
    except sqlite3.ProgrammingError as e:
        print(f"âŒ ERROR: Database connection issue -> {e}")
        return []
    
def get_all_user_groups():
    """Fetch all user groups from the groups table."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM groups;")
    return [dict(row) for row in cursor.fetchall()]

def delete_user_by_id(user_id):
    conn = get_db()
    try:
        with conn:
            # 1. Delete user's group associations
            conn.execute("DELETE FROM user_groups WHERE user_id = ?", (user_id,))
            
            # 2. Delete user's class enrollments
            conn.execute("DELETE FROM class_enrollments WHERE user_id = ?", (user_id,))
            
            # 3. Delete user's individual assignments and their statuses
            # First, get all individual assignment IDs
            individual_assignments = conn.execute(
                "SELECT id FROM individual_assignments WHERE users_id = ?", 
                (user_id,)
            ).fetchall()
            
            # Delete statuses for these individual assignments
            if individual_assignments:
                assignment_ids = [str(ia[0]) for ia in individual_assignments]
                conn.execute(
                    f"DELETE FROM individual_assignment_statuses WHERE individual_assignment_id IN ({','.join(assignment_ids)})"
                )
            
            # Delete individual assignments
            conn.execute("DELETE FROM individual_assignments WHERE users_id = ?", (user_id,))
            
            # 4. Finally, delete the user
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        
        print(f"Successfully deleted user {user_id} and all associated records.")
    except Exception as e:
        conn.rollback()
        print(f"Error deleting user {user_id}: {e}")
        raise e

def add_user_group(name, section='classes'):
    import sqlite3
    from app.database.db import get_db
    print(f"[DEBUG] → add_user_group() called with name={name}, section={section}")

    conn = get_db()

    existing = conn.execute(
        "SELECT 1 FROM groups WHERE LOWER(name) = LOWER(?)",
        (name,)
    ).fetchone()
    if existing:
        raise Exception("A group with this name already exists.")

    try:
        conn.execute(
            "INSERT INTO groups (name, permission_level, section) VALUES (?, 1, ?)",
            (name, section)
        )
        conn.commit()
        print("[DEBUG] ✅ Group inserted successfully")
    except sqlite3.Error as e:
        print(f"[ERROR] SQLite insert failed: {e}")
        raise



def delete_user_group(group_id):
    conn = get_db()

    try:
        dependency_query = "SELECT COUNT(*) FROM user_groups WHERE group_id = ?"
        cursor = conn.execute(dependency_query, (group_id,))
        count = cursor.fetchone()[0]

        if count > 0:
            raise Exception(f"Cannot delete group. It is assigned to {count} users.")

        delete_query = "DELETE FROM groups WHERE id = ?"
        conn.execute(delete_query, (group_id,))
        conn.commit()

    except Exception as e:
        print(f"Error in delete_user_group: {e}")
        raise e

def get_user_groups(user_id):
    conn = get_db()
    try:
        query = """
        SELECT g.id, g.name 
        FROM user_groups ug
        JOIN groups g ON ug.group_id = g.id
        WHERE ug.user_id = ?
        """
        cursor = conn.execute(query, (user_id,))
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.ProgrammingError as e:
        print(f"âŒ ERROR: Database connection issue -> {e}")
        return []

def count_users(filters=None):
    conn = get_db()
    cursor = conn.cursor()

    query = "SELECT COUNT(*) FROM users"
    params = []

    if filters:
        where_clauses = []
        for key, value in filters.items():
            if key == "search":
                where_clauses.append("(name LIKE ? OR login_name LIKE ?)")
                params.extend([f"%{value}%", f"%{value}%"])
            else:
                where_clauses.append(f"{key} = ?")
                params.append(value)

        query += " WHERE " + " AND ".join(where_clauses)

    cursor.execute(query, params)
    return cursor.fetchone()[0]

def add_user_to_class(user_id, class_id, semester):
    """Assign a single user to a class if not already enrolled."""
    query = """
        INSERT INTO class_enrollments (user_id, class_id, semester)
        SELECT ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM class_enrollments
            WHERE class_id = ? AND user_id = ?
        )
    """
    conn = get_db()
    try:
        conn.execute(query, (user_id, class_id, semester, class_id, user_id))
        conn.commit()
        print(f"[OK] Successfully added user {user_id} to class {class_id}")
    except sqlite3.IntegrityError:
        print(f"âš ï¸ User {user_id} is already enrolled in class {class_id}")
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"âŒ Error adding user {user_id} to class {class_id}: {e}")

# ----------------------------------------------------------------------------------------------------------------------
# STUDENTS IN CLASSES ***MAKE SURE TO CHECK THESE
# ----------------------------------------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------------------------------------
# ASSIGNMENT MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def get_assignments(class_id):
    """Fetch all assignments for a specific class, ensuring progress_step_id is included."""
    conn = get_db()
    cursor = conn.cursor()
    
    query = """
    SELECT id, name, start_date, completion_date, progress_step_id 
    FROM assignments 
    WHERE class_id = ?
    """
    
    cursor.execute(query, (class_id,))
    assignments = cursor.fetchall()

    formatted_assignments = []
    for a in assignments:
        assignment_obj = {
            "id": a[0],
            "name": a[1],
            "start_date": a[2],
            "completion_date": a[3],
            "progress_step_id": a[4]  # [OK] Corrected index for renamed column
        }
        formatted_assignments.append(assignment_obj)
    
    return formatted_assignments

def get_assignments_by_class(class_id, conn):
    """Fetch all assignments for a given class."""
    query = """
        SELECT DISTINCT id, name, description, start_date, completion_date
        FROM assignments
        WHERE class_id = ?
    """
    return [dict(row) for row in conn.execute(query, (class_id,)).fetchall()]

def add_assignment_to_db(assignment_data):
    """Creates an assignment and initializes workflows for enrolled students (if any)."""
    conn = get_db()
    try:
        cursor = conn.cursor()
        print(f"ðŸ“¢ Creating assignment with data: {assignment_data}")

        # Auto-calculate max_points from parent_step_id
        max_points_map = {1: 4, 2: 16, 342: 8}
        max_points = max_points_map.get(int(assignment_data["parent_step_id"]), 4)

        cursor.execute("""
            INSERT INTO assignments (class_id, name, start_date, completion_date, parent_step_id, progress_step_id, max_points)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            assignment_data["class_id"],
            assignment_data["name"],
            assignment_data["start_date"],
            assignment_data["completion_date"],
            assignment_data["parent_step_id"],
            assignment_data["progress_step_ids"][0],
            max_points
        ))
        assignment_id = cursor.lastrowid
        print(f"[OK] Assignment {assignment_id} created successfully.")

        # [OK] Insert all selected steps into assignment_progress_steps
        for step_id in assignment_data["progress_step_ids"]:
            cursor.execute("""
                INSERT OR IGNORE INTO assignment_progress_steps (assignment_id, step_id)
                VALUES (?, ?)
            """, (assignment_id, step_id))
        print(f"[OK] Progress steps inserted: {assignment_data['progress_step_ids']}")

        # [OK] Get all steps for this workflow (still needed for default full init)
        cursor.execute("""
            SELECT id, name 
            FROM steps 
            WHERE parent_id = ?
        """, (assignment_data["parent_step_id"],))
        steps = cursor.fetchall()
        print(f"ðŸ“¢ Found steps for workflow: {steps}")

        # [OK] Get students
        if assignment_data["assign_option"] == "all":
            cursor.execute("""
                SELECT user_id 
                FROM class_enrollments 
                WHERE class_id = ?
            """, (assignment_data["class_id"],))
            students = cursor.fetchall()
        else:
            students = [{"user_id": sid} for sid in assignment_data.get("selected_students", [])]

        if not students:
            print("âš ï¸ No students found for this assignment. Skipping individual assignments.")
            conn.commit()
            return assignment_id

        print(f"[OK] Assigning to students: {students}")

        # [OK] Create individual assignments + status records
        for student in students:
            cursor.execute("""
                INSERT INTO individual_assignments 
                (assignment_id, users_id, name, start_date, completion_date)
                VALUES (?, ?, ?, ?, ?)
            """, (
                assignment_id,
                student["user_id"],
                assignment_data["name"],
                assignment_data["start_date"],
                assignment_data["completion_date"]
            ))
            individual_assignment_id = cursor.lastrowid

            for step in steps:
                cursor.execute("""
                    SELECT id, name 
                    FROM nodes 
                    WHERE step_id = ? 
                    ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INTEGER)
                    LIMIT 1
                """, (step["id"],))
                top_node = cursor.fetchone()

                if top_node:
                    cursor.execute("""
                        INSERT INTO individual_assignment_statuses 
                        (individual_assignment_id, step_id, current_status)
                        VALUES (?, ?, ?)
                    """, (
                        individual_assignment_id,
                        step["id"],
                        top_node["name"]
                    ))

        conn.commit()
        print(f"[OK] Successfully assigned students to Assignment {assignment_id}")
        return assignment_id

    except Exception as e:
        conn.rollback()
        print(f"âŒ Error in add_assignment_to_db: {e}")
        raise e

def get_students_in_assignment(assignment_id):
    """Fetch students who are already assigned to the given assignment."""
    query = """
        SELECT u.id, u.name 
        FROM users u
        JOIN individual_assignments ia ON u.id = ia.users_id
        WHERE ia.assignment_id = ?
    """
    conn = get_db()
    return [dict(row) for row in conn.execute(query, (assignment_id,))]

def update_assignment_status(individual_assignment_id, step_id, new_status, conn):
    """Update status and handle crossflows."""
    cursor = conn.cursor()
    
    try:
        # Update primary status
        cursor.execute("""
            UPDATE individual_assignment_statuses
            SET current_status = ?
            WHERE individual_assignment_id = ? AND step_id = ?
        """, (new_status, individual_assignment_id, step_id))
        
        # Find and process crossflows
        cursor.execute("""
            SELECT l.to_flow_id, n.name as target_status, n.color
            FROM links l
            JOIN nodes n ON l.child_node_id = n.id
            WHERE l.parent_node_id IN (
                SELECT id FROM nodes 
                WHERE step_id = ? AND name = ?
            ) AND l.to_flow_id IS NOT NULL
        """, (step_id, new_status))
        
        crossflows = cursor.fetchall()
        
        # Update crossflow statuses
        for flow in crossflows:
            cursor.execute("""
                UPDATE individual_assignment_statuses
                SET current_status = ?
                WHERE individual_assignment_id = ? AND step_id = ?
            """, (flow['target_status'], individual_assignment_id, flow['to_flow_id']))
        
        conn.commit()
        return {
            'success': True,
            'crossflows': [dict(flow) for flow in crossflows]
        }
        
    except Exception as e:
        conn.rollback()
        print(f"Error updating status: {e}")
        raise e
    
def get_assignments_with_progress(class_id):
    """Fetch assignments and add placeholder progress percentages."""
    query = """
    SELECT id, name, start_date, completion_date
    FROM assignments
    WHERE class_id = ?
    """
    conn = get_db()
    rows = conn.execute(query, (class_id,)).fetchall()

    # Convert sqlite3.Row objects to dictionaries and add progress
    assignments = []
    for row in rows:
        assignment = dict(row)  # Convert Row to dictionary
        assignment['progress'] = 50  # Placeholder value for progress
        assignments.append(assignment)

    return assignments

def query_assignments(class_id=None, include_progress=False):
    """
    Query assignments with optional progress information.
    """
    base_query = """
    SELECT a.id, a.name, a.start_date, a.completion_date, a.class_id
    """
    if include_progress:
        base_query += """,
        COUNT(ia.id) AS total_individual_assignments,
        SUM(CASE WHEN ia.status = 'completed' THEN 1 ELSE 0 END) AS completed_assignments
        """
    base_query += " FROM assignments a"

    if include_progress:
        base_query += " LEFT JOIN individual_assignments ia ON a.id = ia.assignment_id"

    where_clauses = []
    params = []

    if class_id:
        where_clauses.append("a.class_id = ?")
        params.append(class_id)

    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)

    if include_progress:
        base_query += " GROUP BY a.id"

    conn = get_db()
    return conn.execute(base_query, params).fetchall()

def get_student_assignments(user_id, class_id):
    """Retrieve assignments only for a specific student in a class."""
    query = """
        SELECT ia.id, ia.assignment_id, ia.name, ia.start_date, ia.completion_date, 
               ia.current_status, ia.file_path, ia.video_status,
               a.class_id, a.name AS assignment_name, a.description,
               u.name AS student_name  -- [OK] Make sure this matches the column name in 'users'
        FROM individual_assignments ia
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN users u ON ia.users_id = u.id  -- [OK] Ensure correct join
        WHERE ia.users_id = ? AND a.class_id = ?
    """
    assignments = query_db(query, (user_id, class_id))

    print(f"ðŸ” Assignments for Student {user_id} in Class {class_id}: {assignments}")  # Debugging

    if assignments:
        print(f"ðŸ” First Assignment Data: {dict(assignments[0])}")  # Print first result as a dictionary

    return assignments

def get_assignment_name_by_id(assignment_id):
    """Fetch the name of an assignment by its ID."""
    query = "SELECT name FROM assignments WHERE id = ?"
    conn = get_db()
    return conn.execute(query, (assignment_id,)).fetchone()['name']

def update_assignment(assignment_id, name, start_date, completion_date):
    """Update an assignment and its associated individual assignments."""
    conn = get_db()
    try:
        cursor = conn.cursor()

        # [OK] Update the main assignment
        cursor.execute("""
            UPDATE assignments
            SET name = ?, start_date = ?, completion_date = ?
            WHERE id = ?
        """, (name, start_date, completion_date, assignment_id))

        # [OK] Update individual assignments linked to this assignment
        cursor.execute("""
            UPDATE individual_assignments
            SET name = ?, start_date = ?, completion_date = ?
            WHERE assignment_id = ?
        """, (name, start_date, completion_date, assignment_id))

        conn.commit()
        print(f"[OK] Successfully updated assignment {assignment_id} and individual assignments.")

    except Exception as e:
        conn.rollback()
        print(f"âŒ Error updating assignment {assignment_id}: {e}")
        raise e

def delete_assignment_from_db(assignment_id):
    """Delete an assignment and all its related data from the database."""
    conn = get_db()
    try:
        cursor = conn.cursor()

        # [OK] Step 1: Fetch all individual assignments for this assignment
        individual_assignments = cursor.execute(
            "SELECT id FROM individual_assignments WHERE assignment_id = ?", (assignment_id,)
        ).fetchall()

        if individual_assignments:
            individual_assignment_ids = [row["id"] for row in individual_assignments]

            # [OK] Step 2: Delete all related individual_assignment_statuses
            cursor.execute(
                "DELETE FROM individual_assignment_statuses WHERE individual_assignment_id IN ({})"
                .format(",".join("?" * len(individual_assignment_ids))),
                individual_assignment_ids
            )

            # [OK] Step 3: Delete all related individual_assignments
            cursor.execute("DELETE FROM individual_assignments WHERE assignment_id = ?", (assignment_id,))

        # [OK] Step 4: Delete the assignment itself
        cursor.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))

        conn.commit()
        print(f"[OK] Successfully deleted assignment {assignment_id} and all related data.")

    except Exception as e:
        conn.rollback()
        print(f"âŒ Error deleting assignment {assignment_id}: {e}")
        raise e

# ----------------------------------------------------------------------------------------------------------------------
# WORKFLOW MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def get_all_workflows():
    """Retrieve all workflows from the steps table."""
    query = "SELECT id, name FROM steps WHERE parent_id IS NULL"
    conn = get_db()
    return [dict(row) for row in conn.execute(query)]

# ----------------------------------------------------------------------------------------------------------------------
# INDIVIDUAL ASSIGNMENT MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def get_individual_assignments_by_assignment(assignment_id, conn):
    query = """
        SELECT ia.id, ia.name, ia.start_date, ia.completion_date, 
               u.name as student_name,
               JSON_GROUP_ARRAY(
                   JSON_OBJECT('step_id', ias.step_id, 'status', ias.current_status)
               ) AS statuses
        FROM individual_assignments ia
        JOIN users u ON ia.users_id = u.id
        JOIN individual_assignment_statuses ias ON ia.id = ias.individual_assignment_id
        WHERE ia.assignment_id = ?
        GROUP BY ia.id
        ORDER BY ia.id ASC;
    """
    return [dict(row) for row in conn.execute(query, (assignment_id,)).fetchall()]

def add_individual_assignment(assignment_id, users_id, assignment_name, start_date, completion_date, current_status):
    """Add an individual assignment and initialize statuses for each step."""
    print(f"Adding Individual Assignment: {assignment_id}, {users_id}, {assignment_name}, {start_date}, {completion_date}, {current_status}")

    insert_query = """
    INSERT INTO individual_assignments (assignment_id, users_id, name, start_date, completion_date)
    VALUES (?, ?, ?, ?, ?)
    """

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(insert_query, (
            assignment_id,
            users_id,
            assignment_name,
            start_date,
            completion_date
        ))
        individual_assignment_id = cursor.lastrowid

        # Fetch steps related to this assignment's workflow
        step_query = """
        SELECT id FROM steps
        WHERE parent_id = (
            SELECT parent_step_id FROM assignments WHERE id = ?
        )
        """
        step_ids = conn.execute(step_query, (assignment_id,)).fetchall()

        # Initialize status for each step
        for row in step_ids:
            step_id = row["id"]

            # [OK] Get the top status for this step
            status_row = conn.execute("""
                SELECT name FROM nodes 
                WHERE step_id = ? 
                ORDER BY CAST(SUBSTR(position, INSTR(position, ' ') + 1) AS INTEGER)
                LIMIT 1
            """, (step_id,)).fetchone()

            default_status = status_row["name"] if status_row else "Not Started"

            # [OK] Insert with proper default
            conn.execute("""
                INSERT INTO individual_assignment_statuses (individual_assignment_id, step_id, current_status)
                VALUES (?, ?, ?)
            """, (individual_assignment_id, step_id, default_status))


        conn.commit()
        print("[OK] Individual assignment and statuses added successfully.")
        return individual_assignment_id

    except Exception as e:
        conn.rollback()
        print(f"âŒ Error adding individual assignment: {e}")
        raise e

def delete_individual_assignment(individual_assignment_id):
    """Delete an individual assignment and its related statuses safely."""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # [OK] Step 1: Delete statuses first (to maintain foreign key integrity)
        cursor.execute(
            "DELETE FROM individual_assignment_statuses WHERE individual_assignment_id = ?",
            [individual_assignment_id]
        )
        
        # [OK] Step 2: Delete the individual assignment itself
        cursor.execute(
            "DELETE FROM individual_assignments WHERE id = ?",
            [individual_assignment_id]
        )

        conn.commit()
        print(f"[OK] Successfully deleted individual assignment {individual_assignment_id}")

    except Exception as e:
        conn.rollback()
        print(f"âŒ Error deleting individual assignment {individual_assignment_id}: {e}")
        raise e  # Rethrow for debugging

# ----------------------------------------------------------------------------------------------------------------------
# NODES MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def add_node(name, step_id, position, status, completion_percentage, color=None):
    """Add a new node to a step."""
    query = """
    INSERT INTO nodes (name, step_id, position, status, completion_percentage, color)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    conn = get_db()
    try:
        conn.execute(query, (
            name, step_id, position, status, completion_percentage, color
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error adding node: {e}")
        raise e

def update_node(node_id, name=None, status=None, completion_percentage=None, color=None):
    """Update an existing node."""
    query = """
    UPDATE nodes
    SET name = COALESCE(?, name),
        status = COALESCE(?, status),
        completion_percentage = COALESCE(?, completion_percentage),
        color = COALESCE(?, color)
    WHERE id = ?
    """
    conn = get_db()
    try:
        conn.execute(query, (name, status, completion_percentage, color, node_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error updating node {node_id}: {e}")
        raise e

def delete_node(node_id):
    """Delete a node by its ID."""
    query = "DELETE FROM nodes WHERE id = ?"
    conn = get_db()
    try:
        conn.execute(query, (node_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error deleting node {node_id}: {e}")
        raise e

def add_node_dependency(parent_node_id, parent_status, child_node_id, child_status):
    """Add a dependency between two nodes."""
    query = """
    INSERT INTO node_dependencies (parent_node_id, parent_status, child_node_id, child_status)
    VALUES (?, ?, ?, ?)
    """
    conn = get_db()
    try:
        conn.execute(query, (parent_node_id, parent_status, child_node_id, child_status))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error adding dependency: {e}")
        raise e

def get_dependencies(node_id):
    """Fetch all dependencies for a specific node."""
    query = """
    SELECT parent_node_id, parent_status, child_node_id, child_status
    FROM node_dependencies
    WHERE parent_node_id = ? OR child_node_id = ?
    """
    conn = get_db()
    return conn.execute(query, (node_id, node_id)).fetchall()

def get_nodes_with_dependencies(step_id):
    """Fetch nodes and their dependencies for a specific step."""
    nodes_query = """
    SELECT id, name, color, completion_percentage, position
    FROM nodes
    WHERE step_id = ?
    ORDER BY position ASC
    """
    dependencies_query = """
    SELECT parent_node_id, child_node_id, parent_status, child_status
    FROM node_dependencies
    JOIN nodes AS parent ON parent_node_id = parent.id
    JOIN nodes AS child ON child_node_id = child.id
    WHERE parent.step_id = ? OR child.step_id = ?
    """
    conn = get_db()
    nodes = conn.execute(nodes_query, (step_id,)).fetchall()
    dependencies = conn.execute(dependencies_query, (step_id, step_id)).fetchall()
    return {"nodes": nodes, "dependencies": dependencies}

def get_workflow_states(individual_assignment_id, conn):
    """Get all workflow states for an individual assignment."""
    cursor = conn.cursor()
    
    # Get assignment's workflow information
    cursor.execute("""
        SELECT a.workflow_id, t.id as step_id, t.name, t.parent_id
        FROM individual_assignments ia
        JOIN assignments a ON ia.assignment_id = a.id
        JOIN steps t ON t.parent_step_id= a.workflow_id
        WHERE ia.id = ? AND t.parent_id IS NOT NULL
    """, (individual_assignment_id,))
    
    workflows = []
    steps = cursor.fetchall()
    
    for steps in steps:
        # Get current status
        cursor.execute("""
            SELECT current_status 
            FROM individual_assignment_statuses
            WHERE individual_assignment_id = ? AND step_id = ?
        """, (individual_assignment_id, steps['step_id']))
        status_row = cursor.fetchone()
        
        # Get available nodes/states for this step
        cursor.execute("""
            SELECT name, color, position
            FROM nodes
            WHERE step_id = ?
            ORDER BY position ASC
        """, (steps['step_id'],))
        nodes = cursor.fetchall()
        
        workflows.append({
            'step_id': steps['step_id'],
            'name': steps['name'],
            'current_status': status_row['current_status'] if status_row else None,
            'available_states': [dict(node) for node in nodes]
        })
    
    return workflows

# ----------------------------------------------------------------------------------------------------------------------
# STATUS MANAGEMENT
# ----------------------------------------------------------------------------------------------------------------------

def update_status(status_id, name=None, color=None):
    """Update an existing status."""
    query = """
    UPDATE statuses
    SET name = COALESCE(?, name),
        color = COALESCE(?, color)
    WHERE id = ?
    """
    conn = get_db()
    try:
        conn.execute(query, (name, color, status_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error updating status {status_id}: {e}")
        raise e

def delete_status(status_id):
    """Delete a status by its ID."""
    query = "DELETE FROM statuses WHERE id = ?"
    conn = get_db()
    try:
        conn.execute(query, (status_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error deleting status {status_id}: {e}")
        raise e

def get_tasks_with_permission(workflow_id, min_permission_level):
    """
    Fetch tasks for a given workflow and minimum permission level.
    """
    query = """
    SELECT id, name, parent_id, min_permission_level
    FROM steps
    WHERE parent_id = ? AND min_permission_level <= ?
    ORDER BY id
    """
    conn = get_db()
    rows = conn.execute(query, (workflow_id, min_permission_level)).fetchall()
    return [dict(row) for row in rows]  # Convert sqlite3.Row objects to dictionaries

# ----------------------------------------------------------------------------------------------------------------------
# STEPS
# ----------------------------------------------------------------------------------------------------------------------

def get_all_steps():
    """Returns raw list of steps with a parent_id."""
    conn = get_db()
    cursor = conn.cursor()
    steps = cursor.execute("""
        SELECT id, name, parent_id
        FROM steps
        WHERE parent_id IS NOT NULL
        ORDER BY order_num
    """).fetchall()
    return steps  # [OK] This returns a list, not a Response

# ----------------------------------------------------------------------------------------------------------------------
# ARCHIVES
# ----------------------------------------------------------------------------------------------------------------------

def get_unarchived_classes():
    """Fetch all unarchived classes."""
    query = """
        SELECT c.id, c.class_name, s.year, s.term AS semester, c.archived
        FROM classes c
        LEFT JOIN semesters s ON c.semester_id = s.id
        WHERE c.archived = 0
        ORDER BY s.year DESC,
            CASE s.term
                WHEN 'Spring' THEN 1
                WHEN 'Summer' THEN 2
                WHEN 'Fall' THEN 3
            END
    """
    conn = get_db()
    return [dict(row) for row in conn.execute(query)]

def get_archived_classes():
    """Fetch all archived classes, with semester label resolved."""
    query = """
        SELECT
            c.id, c.class_name, c.code, c.class_number, c.archived,
            s.year, s.term, s.year || '-' || s.term AS semester_label
        FROM classes c
        LEFT JOIN semesters s ON s.id = c.semester_id
        WHERE c.archived = 1
        ORDER BY s.year DESC, s.term DESC
    """
    conn = get_db()
    return [dict(row) for row in conn.execute(query)]

def get_unarchived_users():
    """Fetch all users who are not archived."""
    query = """
        SELECT id, name, email, created_at
        FROM users
        WHERE archived = 0
        ORDER BY name
    """
    conn = get_db()
    return [dict(row) for row in conn.execute(query)]

def get_archived_users():
    """Fetch all archived users."""
    query = """
        SELECT id, name, email, created_at
        FROM users
        WHERE archived = 1
        ORDER BY name
    """
    conn = get_db()
    return [dict(row) for row in conn.execute(query)]

def get_unarchived_films():
    """Fetch all films that are not archived, with director name and semester label resolved."""
    query = """
        SELECT
            f.id,
            f.name,
            f.description,
            f.created_at,
            u.name AS director_name,
            s.year || '-' || s.term AS semester_label
        FROM films f
        LEFT JOIN users u ON u.id = f.director_id
        LEFT JOIN semesters s ON s.id = f.semester_id
        WHERE f.archived = 0
        ORDER BY f.created_at DESC
    """
    conn = get_db()
    return [dict(row) for row in conn.execute(query)]

def get_archived_films():
    """Fetch all archived films, with director name and semester label resolved."""
    query = """
        SELECT
            f.id, f.name, f.description, f.created_at,
            u.name AS director_name,
            s.year || '-' || s.term AS semester_label
        FROM films f
        LEFT JOIN users u ON u.id = f.director_id
        LEFT JOIN semesters s ON s.id = f.semester_id
        WHERE f.archived = 1
        ORDER BY f.created_at DESC
    """
    conn = get_db()
    return [dict(row) for row in conn.execute(query)]



