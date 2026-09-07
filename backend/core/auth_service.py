"""
core/auth_service.py — Autentikasi & manajemen user via PostgreSQL (Supabase).
"""

from werkzeug.security import generate_password_hash, check_password_hash
from core.db import get_conn, release_conn


class AuthService:

    # ─── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _get_user(username: str) -> dict | None:
        """Ambil satu user dari DB. Return dict atau None."""
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT username, password_hash, role, status FROM users WHERE username = %s",
                    (username,)
                )
                row = cur.fetchone()
            if not row:
                return None
            return {
                'username':      row[0],
                'password_hash': row[1],
                'role':          row[2],
                'status':        row[3],
            }
        finally:
            release_conn(conn)

    # ─── Public API ──────────────────────────────────────────────────────────

    @staticmethod
    def authenticate_user(username: str, password: str):
        """Return (True, user_dict) atau (False, pesan_error)."""
        user = AuthService._get_user(username)

        if not user:
            return False, "User tidak ditemukan"

        if not check_password_hash(user['password_hash'], password):
            return False, "Password salah"

        if user['status'] == 'pending':
            return False, "Akun Anda sedang menunggu persetujuan Admin"

        if user['status'] == 'rejected':
            return False, "Akun Anda telah ditolak oleh Admin"

        return True, user

    @staticmethod
    def register_user(username: str, password: str, role: str = 'krani', status: str = 'pending'):
        """Return (True, pesan) atau (False, pesan_error)."""
        if AuthService._get_user(username):
            return False, "Username sudah digunakan"

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (username, password_hash, role, status)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (username, generate_password_hash(password), role, status)
                )
            conn.commit()
            msg = "Registrasi berhasil, menunggu persetujuan admin" if status == "pending" else "User berhasil ditambahkan"
            return True, msg
        except Exception as e:
            conn.rollback()
            return False, f"Gagal menyimpan user: {e}"
        finally:
            release_conn(conn)

    @staticmethod
    def get_all_users() -> list:
        """Return list semua user (tanpa password_hash)."""
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT username, role, status FROM users ORDER BY username")
                rows = cur.fetchall()
            return [{'username': r[0], 'role': r[1], 'status': r[2]} for r in rows]
        finally:
            release_conn(conn)

    @staticmethod
    def update_user_status(username: str, new_status: str):
        """Return (True, pesan) atau (False, pesan_error)."""
        if new_status not in ('approved', 'rejected', 'pending'):
            return False, "Status tidak valid"

        if username == 'admin':
            return False, "Tidak dapat mengubah status admin utama"

        user = AuthService._get_user(username)
        if not user:
            return False, "User tidak ditemukan"

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET status = %s WHERE username = %s",
                    (new_status, username)
                )
            conn.commit()
            return True, f"Status user {username} berhasil diubah menjadi {new_status}"
        except Exception as e:
            conn.rollback()
            return False, f"Gagal update status: {e}"
        finally:
            release_conn(conn)
