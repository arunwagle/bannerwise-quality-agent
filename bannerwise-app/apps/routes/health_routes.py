"""Health check routes."""

from flask import Blueprint, jsonify

health_bp = Blueprint('health', __name__)


@health_bp.route('/health')
def health():
    """Health check for Databricks App monitoring."""
    return jsonify({
        'status': 'healthy',
        'app': 'bannerwise-quality-agent',
        'version': '0.1.0'
    }), 200
