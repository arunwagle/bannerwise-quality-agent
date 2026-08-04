"""Admin routes — configuration and corpus management."""

from flask import Blueprint, render_template, request, jsonify
from services.corpus_service import get_draft_stats as get_corpus_stats

admin_bp = Blueprint('admin', __name__)

# Mock admin config (would come from env/Delta table in prod)
ADMIN_CONFIG = {
    "confidence_threshold": 0.85,
    "vs_endpoint": "bannerwise-vs-endpoint",
    "vs_index": "catalog.schema.certified_qa_index",
    "serving_endpoint": "bannerwise-quality-router",
    "genie_space_id": "genie-space-mock-001",
}


@admin_bp.route('/admin')
def admin_page():
    """Render the Admin page."""
    return render_template('admin.html')


@admin_bp.route('/api/admin/config', methods=['GET'])
def api_get_config():
    """API: Get current system configuration.

    TODO: Replace with real config from env vars or Delta table.
    """
    stats = get_corpus_stats()
    return jsonify({
        'config': ADMIN_CONFIG,
        'corpus_stats': stats,
        'system_status': {
            'vector_search': 'healthy',
            'serving_endpoint': 'healthy',
            'genie_space': 'healthy',
            'mlflow_tracing': 'active',
        }
    }), 200


@admin_bp.route('/api/admin/config', methods=['PUT'])
def api_update_config():
    """API: Update system configuration.

    Request JSON: {"confidence_threshold": 0.85, ...}

    TODO: Persist to env vars or Delta table.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Update in-memory config (mock — real impl writes to persistent store)
    for key, value in data.items():
        if key in ADMIN_CONFIG:
            ADMIN_CONFIG[key] = value

    return jsonify({'message': 'Configuration updated', 'config': ADMIN_CONFIG}), 200
