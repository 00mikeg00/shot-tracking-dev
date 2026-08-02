from flask import session, redirect, url_for, render_template
from functools import wraps
from werkzeug.security import check_password_hash
from app.database.db import get_db
from datetime import datetime

# =======================================================================================================================================
#  LOGIN PROTECTION DECORATORS
# =======================================================================================================================================

def login_required(view_func):
    """Ensure user is logged in before accessing view."""
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)
    return wrapped_view

def instructor_required(view_func):
    """Shorthand: must be logged in AND have Instructor or Admin role in any section."""
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        
        roles = session.get("roles", {})
        
        # roles can be a dict {section: role_name} or a list of role names
        if isinstance(roles, dict):
            allowed = {"instructor", "admin"}
            if not any(v.lower() in allowed for v in roles.values()):
                return render_template("error_popup.html", 
                    message="Forbidden: Instructor or Admin access required", level="error"), 403
        elif isinstance(roles, list):
            if not any(r.lower() in {"instructor", "admin"} for r in roles):
                return render_template("error_popup.html",
                    message="Forbidden: Instructor or Admin access required", level="error"), 403
        else:
            return render_template("error_popup.html",
                message="Forbidden: No role assigned", level="error"), 403
        
        return view_func(*args, **kwargs)
    return wrapped_view


def admin_required(view_func):
    """Shorthand: must be logged in AND have Admin role."""
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        
        roles = session.get("roles", {})
        
        if isinstance(roles, dict):
            if not any(v.lower() == "admin" for v in roles.values()):
                return render_template("error_popup.html",
                    message="Forbidden: Admin access required", level="error"), 403
        elif isinstance(roles, list):
            if not any(r.lower() == "admin" for r in roles):
                return render_template("error_popup.html",
                    message="Forbidden: Admin access required", level="error"), 403
        else:
            return render_template("error_popup.html",
                message="Forbidden: No role assigned", level="error"), 403
        
        return view_func(*args, **kwargs)
    return wrapped_view

# =======================================================================================================================================
#  PASSWORD AUTHENTICATION
# =======================================================================================================================================

def verify_password(stored_hash, provided_password):
    """Verify the provided password against the stored hash."""
    return check_password_hash(stored_hash, provided_password)

# =======================================================================================================================================
#  ROLE + PERMISSION LOADING (SESSION HELPERS)
# =======================================================================================================================================

def set_user_session(user):
    session.clear()
    session['user_id'] = user['id']
    session['login_name'] = user['login_name']
    session['username'] = user['name']

    raw_roles = get_user_roles(user['id'])

    if isinstance(raw_roles, dict):
        session['roles'] = list(raw_roles.values())
    elif isinstance(raw_roles, str):
        session['roles'] = [raw_roles]
    elif isinstance(raw_roles, list):
        session['roles'] = raw_roles
    else:
        session['roles'] = []

    session['permissions'] = get_user_permission_level(user['id'])

    # Set display_role
    roles_values = session['roles'] if isinstance(session['roles'], list) else list(session['roles'].values())
    if 'Admin' in roles_values:
        session['display_role'] = 'Admin'
    elif 'Instructor' in roles_values:
        session['display_role'] = 'Instructor'
    elif 'TA' in roles_values:
        session['display_role'] = 'TA'
    else:
        session['display_role'] = 'Student'

    session.modified = True
    print("[OK] Session Roles:", session['roles'])

def get_user_roles(user_id):
    """Retrieve a user's roles per section (e.g., 'Instructor', 'TA')."""
    try:
        conn = get_db()
        query = """
            SELECT g.section, g.name
            FROM user_groups ug
            JOIN groups g ON ug.group_id = g.id
            WHERE ug.user_id = ?
        """
        result = conn.execute(query, (user_id,)).fetchall()
        roles = {row['section']: row['name'] for row in result}
        return roles
    except Exception as e:
        print(f" ERROR in get_user_roles(): {e}")
        return {}

def get_user_permission_level(user_id):
    """Retrieve user's highest permission levels for each section (classes, films, etc)."""
    try:
        conn = get_db()
        query = """
            SELECT g.section, MAX(g.permission_level) AS highest_permission
            FROM user_groups ug
            JOIN groups g ON ug.group_id = g.id
            WHERE ug.user_id = ?
            GROUP BY g.section
        """
        result = conn.execute(query, (user_id,)).fetchall()
        permissions = {row['section']: row['highest_permission'] for row in result}
        return permissions
    except Exception as e:
        print(f" ERROR in get_user_permission_level(): {e}")
        return {}

def get_current_semester_id():
    today = datetime.today().date()
    conn = get_db()
    query = """
        SELECT id FROM semesters 
        WHERE start_date <= ? AND end_date >= ? 
        ORDER BY year DESC, term DESC 
        LIMIT 1;
    """
    row = conn.execute(query, (today, today)).fetchone()
    return row["id"] if row else None



