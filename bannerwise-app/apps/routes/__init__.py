"""Routes package — all Flask blueprints for the application."""

from routes.health_routes import health_bp
from routes.quality_routes import quality_bp
from routes.history_routes import history_bp
from routes.corpus_routes import corpus_bp
from routes.admin_routes import admin_bp

__all__ = ['health_bp', 'quality_bp', 'history_bp', 'corpus_bp', 'admin_bp']
