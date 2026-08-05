"""Corpus routes — certification workflow for Q&A entries.

Shows draft entries pending certification. SMEs can certify or reject.
Certified entries are inserted into the certified_qa_corpus table,
which auto-syncs to the Vector Search index.
"""

import logging
import os
from flask import Blueprint, render_template, request, jsonify
from services.corpus_service import (
    get_draft_entries,
    get_draft_by_id,
    get_draft_stats,
    submit_draft,
    certify_entry,
    reject_entry,
)
from databricks.sdk import WorkspaceClient

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
        parameterized_sql: (optional) Modified SQL to certify with
    """
    data = request.get_json() or {}
    certified_by = data.get('certified_by', 'admin@bannerhealth.com')
    modified_sql = data.get('parameterized_sql')

    try:
        result = certify_entry(entry_id, certified_by=certified_by, modified_sql=modified_sql)
        return jsonify(result), 200
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            return jsonify({'error': error_msg}), 404
        # SQL validation failure — return 422 with details for UI display
        return jsonify({'error': error_msg, 'validation_error': True}), 422
    except Exception as e:
        logger.error(f"Failed to certify {entry_id}: {e}")
        return jsonify({'error': str(e)}), 500


@corpus_bp.route('/api/corpus/run-query', methods=['POST'])
def api_corpus_run_query():
    """API: Run a SQL query for SME review preview.

    Request JSON:
        sql: The SQL query to execute
    """
    data = request.get_json() or {}
    sql = data.get('sql', '').strip()
    if not sql:
        return jsonify({'error': 'No SQL query provided'}), 400

    # Only allow read-only queries for safety (SELECT or WITH...SELECT)
    sql_upper = sql.upper().lstrip()
    if not (sql_upper.startswith('SELECT') or sql_upper.startswith('WITH')):
        return jsonify({'error': 'Only SELECT queries are allowed'}), 400

    try:
        w = WorkspaceClient()
        warehouse_id = os.environ.get('SQL_WAREHOUSE_ID', '2d8e531640ffa469')
        response = w.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=sql + ' LIMIT 50',
            wait_timeout='30s',
        )
        if response.status and response.status.state.value == 'FAILED':
            error_msg = response.status.error.message if response.status.error else 'Query failed'
            return jsonify({'error': error_msg}), 200

        # Convert results to list of dicts
        columns = [col.name for col in response.manifest.schema.columns]
        rows = []
        if response.result and response.result.data_array:
            for row in response.result.data_array:
                rows.append(dict(zip(columns, row)))

        return jsonify({'results': rows}), 200
    except Exception as e:
        logger.error(f"Failed to run query: {e}")
        return jsonify({'error': str(e)}), 200


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
