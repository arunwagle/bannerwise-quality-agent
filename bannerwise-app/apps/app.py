"""Bannerwise Quality Agent — Flask application entry point.

Factory pattern creates and configures the app with modular blueprints.
"""

import os
import logging
from flask import Flask, redirect, url_for, session, render_template

from config import get_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app():
    """Application factory — creates and configures the Flask app."""
    app = Flask(__name__)

    # Load configuration
    config = get_config()
    app.config.from_object(config)

    # --- Register Blueprints ---
    from routes.health_routes import health_bp
    from routes.quality_routes import quality_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(quality_bp)

    # --- Root Route ---
    @app.route('/')
    def index():
        """Landing page."""
        return render_template('layout.html')

    # --- Error Handlers ---
    @app.errorhandler(401)
    def unauthorized(e):
        return {'error': 'Unauthorized'}, 401

    @app.errorhandler(403)
    def forbidden(e):
        return {'error': 'Access denied. Insufficient permissions.'}, 403

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Internal server error: {e}")
        return {'error': 'Internal server error occurred.'}, 500

    logger.info("Bannerwise Quality Agent initialized successfully.")
    return app


# Create app instance (gunicorn entry: app:app)
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('DATABRICKS_APP_PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)
