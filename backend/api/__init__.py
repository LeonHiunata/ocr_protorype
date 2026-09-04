from flask import Blueprint

def register_routes(app):
    from middleware.error_handler import register_error_handlers
    from api.ocr_routes import ocr_bp
    from api.gps_routes import gps_bp
    from api.history_routes import history_bp
    from api.auth_routes import auth_bp

    # Register error handlers
    register_error_handlers(app)

    # Register blueprints
    app.register_blueprint(ocr_bp)
    app.register_blueprint(gps_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(auth_bp)
