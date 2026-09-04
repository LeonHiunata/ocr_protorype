import os
import json
import uuid
from werkzeug.security import generate_password_hash, check_password_hash

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

# Pastikan folder data ada
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

class AuthService:
    @staticmethod
    def _load_users():
        if not os.path.exists(USERS_FILE):
            # Inisialisasi default users jika belum ada
            default_users = {
                "admin": {
                    "username": "admin",
                    "password_hash": generate_password_hash("12345"),
                    "role": "admin",
                    "status": "approved"
                },
                "krani": {
                    "username": "krani",
                    "password_hash": generate_password_hash("12345"),
                    "role": "krani",
                    "status": "approved"
                }
            }
            AuthService._save_users(default_users)
            return default_users
        
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def _save_users(users_data):
        with open(USERS_FILE, 'w') as f:
            json.dump(users_data, f, indent=4)

    @staticmethod
    def authenticate_user(username, password):
        users = AuthService._load_users()
        user = users.get(username)
        
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
    def register_user(username, password, role="krani", status="pending"):
        users = AuthService._load_users()
        if username in users:
            return False, "Username sudah digunakan"
            
        users[username] = {
            "username": username,
            "password_hash": generate_password_hash(password),
            "role": role,
            "status": status
        }
        AuthService._save_users(users)
        
        msg = "Registrasi berhasil, menunggu persetujuan admin" if status == "pending" else "User berhasil ditambahkan"
        return True, msg

    @staticmethod
    def get_all_users():
        # Hide password hash when returning to frontend
        users = AuthService._load_users()
        result = []
        for u in users.values():
            result.append({
                "username": u["username"],
                "role": u["role"],
                "status": u["status"]
            })
        return result

    @staticmethod
    def update_user_status(username, new_status):
        if new_status not in ['approved', 'rejected', 'pending']:
            return False, "Status tidak valid"
            
        users = AuthService._load_users()
        if username not in users:
            return False, "User tidak ditemukan"
            
        # Cegah pengubahan status admin default
        if username == 'admin':
            return False, "Tidak dapat mengubah status admin utama"
            
        users[username]['status'] = new_status
        AuthService._save_users(users)
        return True, f"Status user {username} berhasil diubah menjadi {new_status}"
