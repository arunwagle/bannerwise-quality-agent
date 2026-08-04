"""Corpus routes — certification workflow for Q&A entries.

Shows draft entries pending certification. SMEs can certify or reject.
Certified entries are inserted into the certified_qa_corpus table,
which auto-syncs to the Vector Search index.
"""

import logging
from flask import Blueprint, render_template, request, jsonify
from services.corpus_service import (
    get_draft_entries,
    get_draft_by_id,
    get_draft_stats,
    submit_draft,
    certify_entry,
    reject_entry,
)

logger = logging.getLogger(__name__)
corpus_bp = Blueprint('corpus', __name__)


@corpus_bp.route('/corpus')
def corpus_page():
    """Render the Corpus certification page."""
    return render_template('corpus.html')


@corpus_bp.route('/api/corpus/drafts', methods=['GET'])
def api_corpus_drafts():
    """API: Get draft entries pending certification.

    Query params:
        search: Search query against question text
    """
    search = request.args.get('search')
    try:
        entries = get_draft_entries(search=search)
        stats = get_draft_stats()
        return jsonify({'entries': entries, 'stats': stats}), 200
    except Exception as e:
        logger.error(f"Failed to fetch drafts: {e}")
        return jsonify({'error': str(e)}), 500


@corpus_bp.route('/api/corpus/drafts', methods=['POST'])
def api_corpus_submit_draft():
    """API: Submit a new draft for certification.

    Request JSON:
        question: The certified question text
        parameterized_sql: The pre-approved SQL template
        answer_template: Jinja-style answer format
        parameters: List of parameter names
        submitted_by: (optional) Who submitted it
        original_prompt: (optional) The user's original question
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing JSON body'}), 400

    required = ['question', 'parameterized_sql', 'answer_template']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'error': f'Missing required fields: {missing}'}), 400

    try:
        entry = submit_draft(
            question=data['question'],
            parameterized_sql=data['parameterized_sql'],
            answer_template=data['answer_template'],
            parameters=data.get('parameters', []),
            submitted_by=data.get('submitted_by', 'user'),
            original_prompt=data.get('original_prompt'),
        )
        return jsonify(entry), 201
    except Exception as e:
        logger.error(f"Failed to submit draft: {e}")
        return jsonify({'error': str(e)}), 500


@corpus_bp.route('/api/corpus/drafts/<entry_id>', methods=['GET'])
def api_corpus_draft_detail(entry_id):
    """API: Get a single draft entry by ID."""
    try:
        entry = get_draft_by_id(entry_id)
        if not entry:
            return jsonify({'error': 'Draft not found'}), 404
        return jsonify(entry), 200
    except Exception as e:
        logger.error(f"Failed to fetch draft {entry_id}: {e}")
        return jsonify({'error': str(e)}), 500


@corpus_bp.route('/api/corpus/certify/<entry_id>', methods=['POST'])
def api_corpus_certify(entry_id):
    """API: Certify a draft entry.

    Moves the entry from the draft table to the certified_qa_corpus table.
    The Vector Search index will auto-sync the new entry.

    Request JSON:
        certified_by: Email of the certifying SME
    """
    data = request.get_json() or {}
    certified_by = data.get('certified_by', 'admin@bannerhealth.com')

    try:
        result = certify_entry(entry_id, certified_by=certified_by)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Failed to certify {entry_id}: {e}")
        return jsonify({'error': str(e)}), 500


@corpus_bp.route('/api/corpus/reject/<entry_id>', methods=['POST'])
def api_corpus_reject(entry_id):
    """API: Reject/discard a draft entry."""
    try:
        result = reject_entry(entry_id)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.error(f"Failed to reject {entry_id}: {e}")
        return jsonify({'error': str(e)}), 500
