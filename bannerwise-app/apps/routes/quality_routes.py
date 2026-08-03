"""Quality assessment routes — Ask page and API endpoint."""

import os
from flask import Blueprint, render_template, request, jsonify, current_app

quality_bp = Blueprint('quality', __name__)


def _get_router_service():
    """Return the appropriate router service based on API_MODE."""
    api_mode = os.environ.get("API_MODE", "mock")
    if api_mode == "live":
        from services.live_router_service import assess_prompt
    else:
        from services.mock_router_service import assess_prompt
    return assess_prompt


@quality_bp.route('/ask')
def ask_page():
    """Render the Ask page."""
    api_mode = os.environ.get("API_MODE", "mock")
    return render_template('ask.html', api_mode=api_mode)


@quality_bp.route('/api/quality/assess', methods=['POST'])
def api_assess():
    """API: Assess a user prompt through the confidence gate.

    Request JSON: {"prompt": "..."}
    Response JSON: RouterResult (answer, badge, confidence, lane, provenance)

    Uses live Model Serving endpoint when API_MODE=live,
    otherwise falls back to mock service.
    """
    data = request.get_json()
    if not data or not data.get('prompt'):
        return jsonify({'error': 'Missing required field: prompt'}), 400

    assess_prompt = _get_router_service()
    result = assess_prompt(data['prompt'])
    return jsonify(result), 200
