import sys
import os
from flask import Flask, render_template, redirect, session
import uuid

# Import our new API registration
from api import register_routes
from middleware.security import login_required, admin_required

# Attempt to load GPS module to start background process
try:
    from core import gps_reader
    GPS_AVAILABLE = True
except ImportError:
    GPS_AVAILABLE = False
    print("[WARN] gps_reader module not found. GPS features disabled.")

# Initialize the Flask application
app = Flask(__name__, template_folder='../frontend/templates')
app.secret_key = os.urandom(24)

# Register all modular routes and error handlers
register_routes(app)

@app.route("/login", methods=["GET"])
def login_page():
    if 'username' in session:
        return redirect('/admin_dashboard' if session.get('role') == 'admin' else '/')
    return render_template("login.html")

@app.route("/register", methods=["GET"])
def register_page():
    if 'username' in session:
        return redirect('/admin_dashboard' if session.get('role') == 'admin' else '/')
    return render_template("register.html")

@app.route("/", methods=["GET"])
@login_required
def index():
    if session.get('role') == 'admin':
        return redirect('/admin_dashboard')
    return render_template("index.html")

@app.route("/admin_dashboard", methods=["GET"])
@admin_required
def admin_dashboard():
    return render_template("admin_dashboard.html")

# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if GPS_AVAILABLE:
        gps_reader.start()
        print("[GPS] Background GPS reader started.")
    else:
        print("[GPS] GPS reader not available — GPS features will show error in UI.")

    print("Server running at http://127.0.0.1:5000")
    try:
        app.run(debug=True, port=5000, threaded=True, use_reloader=False)
    finally:
        if GPS_AVAILABLE:
            gps_reader.stop()
            print("[GPS] Background GPS reader stopped.")
