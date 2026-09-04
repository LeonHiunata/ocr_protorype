from flask import session, request, jsonify, redirect
from functools import wraps

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            # Jika request dari API (minta JSON)
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({'success': False, 'error': 'Unauthorized, silakan login.'}), 401
            # Jika akses halaman HTML, redirect ke halaman login
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({'success': False, 'error': 'Unauthorized, silakan login.'}), 401
            return redirect('/login')
            
        if session.get('role') != 'admin':
            if request.path.startswith('/api/') or request.is_json:
                return jsonify({'success': False, 'error': 'Forbidden, hanya admin yang diizinkan.'}), 403
            # Redirect ke dashboard krani jika bukan admin
            return redirect('/')
            
        return f(*args, **kwargs)
    return decorated_function
