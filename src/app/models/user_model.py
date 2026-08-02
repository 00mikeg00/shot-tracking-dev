# src/app/models/user_model.py

from app.database.db import query_db, modify_db, get_db

class User:
    @staticmethod
    def get_by_id(user_id: int) -> dict:
        user = query_db('SELECT * FROM users WHERE id = ?', (user_id,), one=True)
        return dict(user) if user else None

    @staticmethod
    def get_all(limit: int = 100, offset: int = 0) -> list:
        users = query_db('SELECT * FROM users LIMIT ? OFFSET ?', (limit, offset))
        return [dict(user) for user in users]

    @staticmethod
    def create(name: str, login_name: str, email: str, password: str, graduation_year: int = None) -> int:
        return modify_db(
            'INSERT INTO users (name, login_name, email, password_hash, graduation_year) VALUES (?, ?, ?, ?, ?)',
            (name, login_name, email, password, graduation_year)
        )

    @staticmethod
    def update(user_id: int, name: str = None, login_name: str = None, email: str = None,
               permission_level: int = None, graduation_year="__unset__"):

        fields = []
        params = []

        if name:
            fields.append("name = ?")
            params.append(name)
        if login_name:
            fields.append("login_name = ?")
            params.append(login_name)
        if email:
            fields.append("email = ?")
            params.append(email)
        if permission_level is not None:
            fields.append("permission_level = ?")
            params.append(permission_level)
        if graduation_year != "__unset__":
            fields.append("graduation_year = ?")
            params.append(graduation_year if graduation_year not in (None, "") else None)

        if not fields:
            raise ValueError("No fields provided for update.")

        params.append(user_id)

        query = f"UPDATE users SET {', '.join(fields)} WHERE id = ?"
        modify_db(query, tuple(params))

    @staticmethod
    def delete(user_id: int) -> None:
        conn = get_db()
        try:
            with conn:
                # 1. Delete user's group associations
                conn.execute("DELETE FROM user_groups WHERE user_id = ?", (user_id,))

                # 2. Delete user's class enrollments
                conn.execute("DELETE FROM class_enrollments WHERE user_id = ?", (user_id,))

                # 3. Delete user's individual assignments and their statuses
                individual_assignments = conn.execute(
                    "SELECT id FROM individual_assignments WHERE users_id = ?",
                    (user_id,)
                ).fetchall()

                if individual_assignments:
                    assignment_ids = [str(ia["id"]) for ia in individual_assignments]
                    conn.execute(
                        f"DELETE FROM individual_assignment_statuses WHERE individual_assignment_id IN ({','.join(assignment_ids)})"
                    )

                # 4. Delete individual assignments
                conn.execute("DELETE FROM individual_assignments WHERE users_id = ?", (user_id,))

                # 5. Finally, delete the user
                conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

            print(f"[OK] Successfully deleted user {user_id} and all associated records.")
        except Exception as e:
            conn.rollback()
            print(f"❌ Error deleting user {user_id}: {e}")
            raise e

    @staticmethod
    def find_by_login_name(login_name: str) -> dict:
        user = query_db('SELECT * FROM users WHERE login_name = ?', (login_name,), one=True)
        return dict(user) if user else None

    @staticmethod
    def search_by_name(search_term: str) -> list:
        search_term = f"%{search_term}%"
        users = query_db('SELECT * FROM users WHERE name LIKE ?', (search_term,))
        return [dict(user) for user in users]

    @staticmethod
    def get_group_ids(user_id: int) -> list:
        db = get_db()
        query = "SELECT group_id FROM user_groups WHERE user_id = ?"
        return [row["group_id"] for row in db.execute(query, (user_id,))]

    @staticmethod
    def get_class_ids(user_id: int) -> list:
        db = get_db()
        query = "SELECT class_id FROM class_enrollments WHERE user_id = ?"
        return [row["class_id"] for row in db.execute(query, (user_id,))]

    @staticmethod
    def get_classes(user_id: int) -> list:
        db = get_db()
        query = """
            SELECT c.* FROM classes c
            INNER JOIN class_enrollments ce ON c.id = ce.class_id
            WHERE ce.user_id = ?
        """
        return [dict(row) for row in db.execute(query, (user_id,))]

    @staticmethod
    def get_users_in_groups(group_ids: list) -> list:
        db = get_db()
        placeholders = ",".join("?" for _ in group_ids)
        query = f"SELECT * FROM users WHERE id IN (SELECT user_id FROM user_groups WHERE group_id IN ({placeholders}))"
        return [dict(row) for row in db.execute(query, group_ids)]

    @staticmethod
    def get_enrolled(class_id: int, semester: str = None, user_id: int = None) -> list | bool:
        db = get_db()
        query = """
            SELECT users.id, users.name, users.email
            FROM users
            JOIN class_enrollments ON users.id = class_enrollments.user_id
            WHERE class_enrollments.class_id = ?
        """
        params = [class_id]

        if semester:
            query += " AND class_enrollments.semester = ?"
            params.append(semester)

        if user_id:
            query += " AND users.id = ?"
            params.append(user_id)

        result = db.execute(query, params)

        if user_id:
            return result.fetchone() is not None

        return [dict(row) for row in result.fetchall()]

    @staticmethod
    def get_not_in_class(class_id: int) -> list:
        db = get_db()
        query = """
            SELECT u.id, u.name, u.email
            FROM users u
            JOIN user_groups ug ON u.id = ug.user_id
            WHERE ug.group_id = 1
              AND u.id NOT IN (
                  SELECT user_id FROM class_enrollments WHERE class_id = ?
              )
            ORDER BY u.name
        """
        return [dict(row) for row in db.execute(query, (class_id,))]

    @staticmethod
    def get_not_in_any_active_class() -> list:
        db = get_db()
        query = """
            SELECT u.id, u.name, u.email, u.archived, u.graduation_year
            FROM users u
            WHERE u.id NOT IN (
                SELECT ce.user_id
                FROM class_enrollments ce
                JOIN classes c ON ce.class_id = c.id
                WHERE c.archived = 0
            ) AND u.archived = 0
        """
        return [dict(row) for row in db.execute(query)]