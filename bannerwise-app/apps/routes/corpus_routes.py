"""Corpus routes — browse certified Q&A entries."""

from flask import Blueprint, render_template, request, jsonify
from services.mock_corpus_service import get_all_entries, get_entry_by_id, get_corpus_stats

corpus_bp = Blueprint('corpus', __name__)


@corpus_bp.route('/corpus')
def corpus_page():
    """Render the Corpus browse page."""
    return render_template('corpus.html')


@corpus_bp.route('/api/corpus', methods=['GET'])
def api_corpus_list():
    """API: Get corpus entries.

    Query params:
        status: Filter by status (certified, draft, expired)
        search: Search query against question text

    TODO: Replace mock_corpus_service with real Delta table query.
    """
    status_filter = request.args.get('status')
    search = request.args.get('search')

    entries = get_all_entries(status_filter=status_filter, search=search)
    stats = get_corpus_stats()

    return jsonify({'entries': entries, 'stats': stats}), 200


@corpus_bp.route('/api/corpus/<entry_id>', methods=['GET'])
def api_corpus_detail(entry_id):
    """API: Get a single corpus entry by ID."""
    entry = get_entry_by_id(entry_id)
    if not entry:
        return jsonify({'error': 'Entry not found'}), 404
    return jsonify(entry), 200
