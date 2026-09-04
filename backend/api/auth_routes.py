from flask import Blueprint, request, jsonify, session, redirect, url_for
from functools import wraps
from core.auth_service import AuthService
from middleware.error_handler import APIError
from middleware.security import login_required, admin_required

auth_bp = Blueprint('auth', __name__)

@auth_bp.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        raise APIError("Username dan Password wajib diisi", 400)
        
    success, result = AuthService.authenticate_user(username, password)
    
    if not success:
        # result adalah string pesan error
        raise APIError(result, 401)
        
    # Set session
    user_data = result
    session['username'] = user_data['username']
    session['role'] = user_data['role']
    
    # Tentukan redirect url berdasarkan role
    redirect_url = '/admin_dashboard' if user_data['role'] == 'admin' else '/'
    
    return jsonify({
        "success": True,
        "message": f"Login berhasil sebagai {user_data['role']}",
        "role": user_data['role'],
        "redirect": redirect_url
    })

@auth_bp.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    username = data.get('username')
    password = data.get('password')
    role = 'krani' # Pendaftar publik pasti user (krani)
    
    if not username or not password:
        raise APIError("Username dan Password wajib diisi", 400)
        
    success, msg = AuthService.register_user(username, password, role, status="pending")
    if not success:
        raise APIError(msg, 400)
        
    return jsonify({
        "success": True,
        "message": msg
    })

@auth_bp.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "Berhasil logout", "redirect": "/login"})

@auth_bp.route("/api/admin/users", methods=["GET"])
@admin_required
def get_users():
    users = AuthService.get_all_users()
    return jsonify({"success": True, "users": users})

@auth_bp.route("/api/admin/users/status", methods=["POST"])
@admin_required
def update_user_status():
    data = request.get_json(force=True)
    username = data.get('username')
    status = data.get('status')
    
    if not username or not status:
        raise APIError("Username dan Status wajib diisi", 400)
        
    success, msg = AuthService.update_user_status(username, status)
    if not success:
        raise APIError(msg, 400)
        
    return jsonify({"success": True, "message": msg})

@auth_bp.route("/api/admin/users/add", methods=["POST"])
@admin_required
def admin_add_user():
    data = request.get_json(force=True)
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'krani')
    
    if not username or not password:
        raise APIError("Username dan Password wajib diisi", 400)
        
    success, msg = AuthService.register_user(username, password, role=role, status="approved")
    if not success:
        raise APIError(msg, 400)
        
    return jsonify({"success": True, "message": msg})
