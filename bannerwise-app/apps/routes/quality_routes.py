"""Quality assessment routes — Ask page and API endpoint."""

import os
import logging
from flask import Blueprint, render_template, request, jsonify, current_app
from services.history_service import log_query

logger = logging.getLogger(__name__)

quality_bp = Blueprint('quality', __name__)


def _get_router_service():
    """Return the appropriate router service based on API_MODE."""
    api_mode = os.environ.get("API_MODE", "mock")
    if api_mode == "live":
        from services.live_router_service import assess_prompt
    else:
        from services.demo_router_service import assess_prompt
    return assess_prompt


@quality_bp.route('/ask')
def ask_page():
    """Render the Ask page."""
    api_mode = os.environ.get("API_MODE", "mock")
    return render_template('ask.html', api_mode=api_mode)


@quality_bp.route('/demo')
def demo_page():
    """Render the Demo Scenarios page."""
    return render_template('demo.html')


@quality_bp.route('/api/quality/assess', methods=['POST'])
def api_assess():
    """API: Assess a user prompt through the confidence gate.

    Request JSON: {"prompt": "..."}
    Response JSON: RouterResult (answer, badge, confidence, lane, provenance)

    Uses live Model Serving endpoint when API_MODE=live,
    otherwise falls back to mock service.
    """
    data = request.get_json(force=True, silent=True)
    if not data or not data.get('prompt'):
        return jsonify({'error': 'Missing required field: prompt'}), 400

    try:
        assess_prompt = _get_router_service()
        result = assess_prompt(data['prompt'])
    except Exception as e:
        logger.error(f"assess_prompt failed unexpectedly: {e}")
        result = {
            "answer": f"An error occurred while processing your question: {str(e)[:200]}",
            "badge": "ERROR",
            "confidence": 0.0,
            "lane": "error",
            "provenance": {"error": str(e)},
            "latency_ms": 0,
        }

    # Log to query history (async-safe, won't block response on failure)
    try:
        log_query({
            "prompt": data['prompt'],
            "lane": result.get("lane"),
            "confidence": result.get("confidence"),
            "badge": result.get("badge"),
            "corpus_id": result.get("corpus_id"),
            "sql_executed": result.get("sql_executed", ""),
            "answer": result.get("answer") or "",
            "latency_ms": result.get("latency_ms", 0),
            "user_email": "app_user",
        })
    except Exception as e:
        logger.warning(f"Failed to log query history: {e}")

    return jsonify(result), 200
