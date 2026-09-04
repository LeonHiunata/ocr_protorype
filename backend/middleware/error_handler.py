from flask import jsonify

class APIError(Exception):
    """Custom API exception for structured error responses."""
    def __init__(self, message, status_code=400, payload=None):
        super().__init__()
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['error'] = self.message
        return rv

def register_error_handlers(app):
    @app.errorhandler(APIError)
    def handle_api_error(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        return response

    @app.errorhandler(404)
    def handle_404(error):
        return jsonify({'error': 'Resource not found.'}), 404

    @app.errorhandler(500)
    def handle_500(error):
        return jsonify({'error': 'Internal server error.', 'details': str(error)}), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        # pass through HTTP errors
        if hasattr(e, 'code') and isinstance(e.code, int):
            return jsonify({'error': str(e)}), e.code
        # return a generic 500 with details for unhandled exceptions
        return jsonify({'error': 'An unexpected error occurred.', 'details': str(e)}), 500
