"""History routes — past queries page and API."""

from flask import Blueprint, render_template, request, jsonify
from services.history_service import get_history, get_history_stats

history_bp = Blueprint('history', __name__)


@history_bp.route('/history')
def history_page():
    """Render the History page."""
    return render_template('history.html')


@history_bp.route('/api/history', methods=['GET'])
def api_history():
    """API: Get query history.

    Query params:
        lane: Filter by lane (certified, analytical)
        limit: Max entries (default 50)

    TODO: Replace mock_history_service with real Delta table query.
    """
    lane_filter = request.args.get('lane')
    limit = request.args.get('limit', 50, type=int)

    entries = get_history(lane_filter=lane_filter, limit=limit)
    stats = get_history_stats()

    return jsonify({'entries': entries, 'stats': stats}), 200
