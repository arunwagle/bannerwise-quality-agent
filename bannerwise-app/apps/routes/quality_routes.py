"""Quality assessment routes — Ask page and API endpoint."""

from flask import Blueprint, render_template, request, jsonify
from services.mock_router_service import assess_prompt

quality_bp = Blueprint('quality', __name__)


@quality_bp.route('/ask')
def ask_page():
    """Render the Ask page."""
    return render_template('ask.html')


@quality_bp.route('/api/quality/assess', methods=['POST'])
def api_assess():
    """API: Assess a user prompt through the confidence gate.

    Request JSON: {"prompt": "..."}
    Response JSON: RouterResult (answer, badge, confidence, lane, provenance)

    TODO: Replace mock_router_service.assess_prompt() with real
          Model Serving endpoint call.
    """
    data = request.get_json()
    if not data or not data.get('prompt'):
        return jsonify({'error': 'Missing required field: prompt'}), 400

    result = assess_prompt(data['prompt'])
    return jsonify(result), 200
