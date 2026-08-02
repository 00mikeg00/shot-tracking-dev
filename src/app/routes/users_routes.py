# src/app/routes/users_routes.py

from flask import Blueprint, render_template, request, flash, redirect, url_for, session, jsonify, current_app
from app.models import hash_password, query_users, count_users, get_all_groups, get_user_groups, add_user_to_class, delete_user_by_id
from app.models.user_model import User
from app.utils.utils import flash_and_redirect
from app.utils.auth_utils import login_required, admin_required
from app.database.db import get_db
from werkzeug.security import check_password_hash

users_bp = Blueprint('users', __name__)

# ----------------------------------------------------------------------------------------------------------------------
# UTILITIES
# ----------------------------------------------------------------------------------------------------------------------

def assign_groups(user_id: int, group_ids: list[int]) -> None:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_groups WHERE user_id=?", (user_id,))
    for group_id in group_ids:
        if group_id:
            cursor.execute("INSERT INTO user_groups (user_id, group_id) VALUES (?, ?)", (user_id, int(group_id)))
    conn.commit()

def get_user_by_id(user_id: int):
    users = query_users(filters={'id': user_id})
    return users[0] if users else None

def get_artist_group_id():
    return next((g['id'] for g in get_all_groups() if g['name'].lower() == 'artist'), None)

def validate_required_fields(form_data: dict, required_fields: list) -> None:
    for field in required_fields:
        if not form_data.get(field):
            raise ValueError(f"Field {field} is required.")

def get_selected_group_ids_from_form() -> list[int]:
    """Extract selected group IDs from the form as integers."""
    return [int(group_id) for group_id in request.form.getlist("user_group[]") if group_id]

def calculate_total_pages(total_items: int, items_per_page: int) -> int:
    return (total_items + items_per_page - 1) // items_per_page


# ----------------------------------------------------------------------------------------------------------------------
# USERS
# ----------------------------------------------------------------------------------------------------------------------

@users_bp.route('/users', methods=['GET'])
@admin_required  
def view_users():
    search_query = request.args.get('search', '')
    page = int(request.args.get('page', 1))
    per_page = 10
    offset = (page - 1) * per_page

    filters = {}
    if search_query:
        filters['search'] = search_query
    users = query_users(filters=filters, limit=per_page, offset=offset)
    users_dict = [dict(user) for user in users]

    total_users = count_users(filters)
    total_pages = calculate_total_pages(total_users, per_page)

    return render_template('users/users.html', users=users_dict, search_query=search_query, current_page=page, total_pages=total_pages)

@users_bp.route('/add_user', methods=['GET', 'POST'])
def add_user():
    all_groups = get_all_groups()
    
    if request.method == 'POST':
        form = request.form

        # Validate basic fields
        try:
            validate_required_fields(form, ['name', 'login_name', 'email_local', 'email_domain', 'password', 'confirm_password'])
        except ValueError as e:
            return flash_and_redirect(str(e), 'danger', 'users.add_user')

        if form['password'] != form['confirm_password']:
            return flash_and_redirect('Passwords do not match.', 'danger', 'users.add_user')

        try:
            # [OK] Correctly construct full email
            email_local = form['email_local']
            email_domain = form['email_domain']
            full_email = f"{email_local}@{email_domain}"

            hashed_password = hash_password(form['password'])

            graduation_year = form.get('graduation_year') or None

            # [OK] Create user with constructed email
            user_id = User.create(
                name=form['name'],
                login_name=form['login_name'],
                email=full_email,
                password=hashed_password,
                graduation_year=graduation_year
            )


            # [OK] Assign groups if selected
            selected_group_ids = get_selected_group_ids_from_form()
            if selected_group_ids:
                assign_groups(user_id, selected_group_ids)

            return flash_and_redirect('User added successfully!', 'success', 'users.view_users')

        except Exception as e:
            print(f"âŒ Exception in add_user: {e}")
            return flash_and_redirect(f"Error adding user: {e}", 'danger', 'users.add_user')

    return render_template(
        'users/add_user.html',
        all_groups=all_groups,
        user_groups=[],
        artist_id = get_artist_group_id()

)

@users_bp.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    user = User.get_by_id(user_id)
    if not user:
        return flash_and_redirect('User not found.', 'danger', 'users.view_users')

    all_groups = get_all_groups()
    user_groups = get_user_groups(user_id)
    user_group_ids = [group['id'] for group in user_groups] if user_groups else []

    if request.method == "POST":
        try:
            form_data = request.form
            validate_required_fields(form_data, ['name', 'login_name'])

            new_name = form_data['name']
            new_login_name = form_data['login_name']
            new_email = form_data['email']
            new_graduation_year = form_data.get('graduation_year') or None

            User.update(
                user_id=user_id,
                name=new_name,
                login_name=new_login_name,
                email=new_email,
                graduation_year=new_graduation_year
            )


            # [OK] Update groups
            selected_group_ids = get_selected_group_ids_from_form()
            assign_groups(user_id, selected_group_ids)

            return flash_and_redirect('User updated successfully!', 'success', 'users.view_users')

        except Exception as e:
            return flash_and_redirect(f"Error updating user: {e}", 'danger', 'users.edit_user', user_id=user_id)

    return render_template('users/edit_user.html', user=user, all_groups=all_groups, user_groups=user_group_ids)

@users_bp.route('/users/delete/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    try:
        delete_user_by_id(user_id)
        return flash_and_redirect('User deleted successfully!', 'success', 'users.view_users')
    except Exception as e:
        return flash_and_redirect(f"Error deleting user: {e}", 'danger', 'users.view_users')

@users_bp.route('/admin/users/<int:user_id>/assign_class', methods=['POST'])
@admin_required
def assign_user_to_class(user_id):

    class_id = request.form['class_id']
    semester = request.form['semester']

    try:
        add_user_to_class(user_id, class_id, semester)
        return flash_and_redirect('Class assigned successfully!', 'success', 'users.view_users')
    except Exception as e:
        return flash_and_redirect(f'Error assigning class: {e}', 'danger', 'users.view_users')

@users_bp.route('/assign_group', methods=['POST'])
@admin_required
def assign_group_route():
    user_id = request.form.get('user_id')
    group_id = request.form.get('group_id')

    if not user_id or not group_id:
        return flash_and_redirect('User ID and Group ID are required.', 'danger', 'users.view_users')

    try:
        assign_groups(user_id, [group_id])
        return flash_and_redirect(f'Group {group_id} assigned to User {user_id} successfully!', 'success', 'users.view_users')
    except Exception as e:
        return flash_and_redirect(f'Error assigning group: {e}', 'danger', 'users.view_users')


@users_bp.route('/api/by_login/<login_name>', methods=['GET'])
def get_user_by_login(login_name):
    conn = get_db()
    row = conn.execute(
        "SELECT id, name, login_name FROM users WHERE login_name = ?",
        (login_name,)
    ).fetchone()
    if not row:
        return jsonify({"error": "User not found"}), 404
    return jsonify(dict(row))

@users_bp.route('/change_password', methods=['POST'])
@login_required
def user_change_password():
    """
    Logged-in user changes their own password.
    Detects whether the DB uses 'password' or 'password_hash' column and updates that.
    """
    conn = None
    try:
        data = request.get_json(silent=True) or {}
        current_pw = (data.get('current_password') or '').strip()
        new_pw     = (data.get('new_password') or '').strip()

        if not current_pw or not new_pw:
            return jsonify({'error': 'Missing fields'}), 400
        if len(new_pw) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400

        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401

        conn = get_db()
        cur = conn.cursor()

        # Figure out which column the users table actually uses
        cols = cur.execute('PRAGMA table_info(users)').fetchall()
        col_names = [ (c['name'] if hasattr(c, 'keys') else c[1]) for c in cols ]
        pw_col = 'password' if 'password' in col_names else ('password_hash' if 'password_hash' in col_names else None)
        if not pw_col:
            current_app.logger.error("change_pw: no password/password_hash column in users table (cols=%s)", col_names)
            return jsonify({'error': 'Server misconfiguration: password column not found'}), 500

        # Get stored hash
        row = cur.execute(f'SELECT {pw_col} FROM users WHERE id = ?', (user_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'User not found'}), 404

        stored_hash = row[pw_col] if hasattr(row, 'keys') else row[0]
        try:
            if not check_password_hash(stored_hash, current_pw):
                return jsonify({'error': 'Current password is incorrect'}), 400
        except Exception:
            current_app.logger.exception("change_pw: invalid stored hash format")
            return jsonify({'error': 'Server misconfiguration: invalid stored password hash'}), 500

        # Update with new hash
        new_hash = hash_password(new_pw)   # uses your existing helper
        cur.execute(f'UPDATE users SET {pw_col} = ? WHERE id = ?', (new_hash, user_id))
        conn.commit()

        return jsonify({'ok': True})
    except Exception:
        current_app.logger.exception("ðŸ”´ change_pw failed")
        return jsonify({'error': 'Internal Server Error'}), 500
    finally:
        try:
            if conn: conn.close()
        except Exception:
            pass

# ----------------------------------------------------------------------------------------------------------------------
# ADMIN
# ----------------------------------------------------------------------------------------------------------------------

@users_bp.route('/change_password/<int:user_id>', methods=['POST'])
@login_required
def change_password(user_id):
    from app.models import update_user_password

    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    if not new_password or not confirm_password:
        return flash_and_redirect('Password fields cannot be empty.', 'danger', 'users.edit_user', user_id=user_id)

    if new_password != confirm_password:
        return flash_and_redirect('Passwords do not match.', 'danger', 'users.edit_user', user_id=user_id)

    hashed_password = hash_password(new_password)
    update_user_password(user_id, hashed_password)

    return flash_and_redirect('Password updated successfully!', 'success', 'users.edit_user', user_id=user_id)



