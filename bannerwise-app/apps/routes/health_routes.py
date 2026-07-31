"""Health check routes."""

from flask import Blueprint

health_bp = Blueprint('health', __name__)


@health_bp.route('/health')
def health():
    """Health check for Databricks App monitoring."""
    return {'status': 'healthy', 'app': 'bannerwise-quality-agent'}, 200
