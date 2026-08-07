"""Live Corpus Service — manages the certification workflow.

Flow:
1. User corrects/selects a query from Ask page → submit_draft() → inserts into draft table
2. Corpus page shows pending drafts → get_draft_entries()
3. SME clicks Certify → certify_entry() → moves row from draft to certified table
4. Vector Search index auto-syncs from certified table (Delta Sync)
"""

import os
import re
import json
import uuid
import logging
from datetime import datetime, date, timedelta
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

logger = logging.getLogger(__name__)

# Configuration
CATALOG = os.environ.get("CATALOG_NAME", "aw_serverless_stable_catalog")
SCHEMA = os.environ.get("SCHEMA_NAME", "bannerhealth")
SQL_WAREHOUSE_ID = os.environ.get("SQL_WAREHOUSE_ID", "2d8e531640ffa469")
VS_INDEX_NAME = f"{CATALOG}.{SCHEMA}.certified_qa_index"

DRAFT_TABLE = f"{CATALOG}.{SCHEMA}.certified_qa_corpus_draft"
CERTIFIED_TABLE = f"{CATALOG}.{SCHEMA}.certified_qa_corpus"


def generate_embedding_text(question: str) -> str:
    """Generate embedding-optimized text by stripping {param} placeholders.

    Decouples RETRIEVAL (VS matching on analytical intent) from
    VALIDATION (LLM judge uses original parameterized question).
    """
    stripped = re.sub(r'\{[^}]+\}', '', question)
    stripped = re.sub(r'\s+', ' ', stripped).strip()
    stripped = re.sub(r'\s+(for|in|by|the|this|from)\s*\??$', '?', stripped)
    return stripped


def _get_client():
    """Get authenticated WorkspaceClient."""
    return WorkspaceClient()


def _execute_sql(w, sql: str, wait_timeout: str = "30s") -> dict:
    """Execute SQL and return response."""
    response = w.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=SQL_WAREHOUSE_ID,
        wait_timeout=wait_timeout,
    )
    if response.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL execution failed: {response.status.error}")
    return response


def _rows_to_dicts(response) -> list:
    """Convert SQL response to list of dicts."""
    if not response.result or not response.result.data_array:
        return []
    columns = [col.name for col in response.manifest.schema.columns]
    return [dict(zip(columns, row)) for row in response.result.data_array]


def get_draft_entries(search: str = None) -> list:
    """Get all draft entries pending certification.

    Args:
        search: Optional search filter on question text.

    Returns:
        List of draft entry dicts.
    """
    w = _get_client()

    sql = f"""
    SELECT id, question, parameterized_sql, answer_template, parameters,
           submitted_by, original_prompt, created_at
    FROM {DRAFT_TABLE}
    ORDER BY created_at DESC
    """

    response = _execute_sql(w, sql)
    entries = _rows_to_dicts(response)

    # Parse parameters JSON string back to list
    for entry in entries:
        if entry.get("parameters") and isinstance(entry["parameters"], str):
            try:
                entry["parameters"] = json.loads(entry["parameters"])
            except json.JSONDecodeError:
                entry["parameters"] = []

    # Apply search filter in-memory (small dataset)
    if search:
        search_lower = search.lower()
        entries = [e for e in entries if search_lower in (e.get("question") or "").lower()]

    return entries


def get_draft_stats() -> dict:
    """Get summary statistics about drafts pending certification."""
    w = _get_client()
    sql = f"SELECT COUNT(*) as total FROM {DRAFT_TABLE}"
    response = _execute_sql(w, sql)
    rows = _rows_to_dicts(response)
    total = int(rows[0]["total"]) if rows else 0
    return {"pending": total}


def get_draft_by_id(entry_id: str) -> dict:
    """Get a single draft entry by ID."""
    w = _get_client()
    sql = f"""
    SELECT id, question, parameterized_sql, answer_template, parameters,
           submitted_by, original_prompt, created_at
    FROM {DRAFT_TABLE}
    WHERE id = '{entry_id}'
    """
    response = _execute_sql(w, sql)
    entries = _rows_to_dicts(response)
    if not entries:
        return None
    entry = entries[0]
    if entry.get("parameters") and isinstance(entry["parameters"], str):
        try:
            entry["parameters"] = json.loads(entry["parameters"])
        except json.JSONDecodeError:
            entry["parameters"] = []
    return entry


def submit_draft(
    question: str,
    parameterized_sql: str,
    answer_template: str,
    parameters: list,
    submitted_by: str = "user",
    original_prompt: str = None,
) -> dict:
    """Submit a new draft entry for certification.

    Called when a user corrects/selects a query from the Ask page.

    Returns:
        The created draft entry dict.
    """
    w = _get_client()

    entry_id = f"DRAFT-{uuid.uuid4().hex[:8].upper()}"
    params_json = json.dumps(parameters) if parameters else "[]"
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    # Escape single quotes in strings for SQL
    question_escaped = question.replace("'", "''")
    sql_escaped = parameterized_sql.replace("'", "''")
    template_escaped = answer_template.replace("'", "''")
    original_escaped = (original_prompt or "").replace("'", "''")
    submitted_escaped = submitted_by.replace("'", "''")

    insert_sql = f"""
    INSERT INTO {DRAFT_TABLE}
    (id, question, parameterized_sql, answer_template, parameters, submitted_by, original_prompt, created_at)
    VALUES (
        '{entry_id}',
        '{question_escaped}',
        '{sql_escaped}',
        '{template_escaped}',
        '{params_json}',
        '{submitted_escaped}',
        '{original_escaped}',
        '{now}'
    )
    """

    _execute_sql(w, insert_sql)
    logger.info(f"Draft submitted: {entry_id} by {submitted_by}")

    return {
        "id": entry_id,
        "question": question,
        "parameterized_sql": parameterized_sql,
        "answer_template": answer_template,
        "parameters": parameters,
        "submitted_by": submitted_by,
        "original_prompt": original_prompt,
        "created_at": now,
    }


def _validate_sql(w, sql: str, parameters: list = None) -> None:
    """Validate SQL syntax before certification using EXPLAIN.

    Substitutes parameter placeholders (:param) with dummy values so that
    EXPLAIN can parse the query. Raises ValueError if SQL is invalid.
    """
    test_sql = sql

    # Replace :param placeholders with dummy string values for validation
    if parameters:
        for param in parameters:
            if isinstance(param, str) and param.strip():
                test_sql = test_sql.replace(f":{param}", "'__VALIDATION_PLACEHOLDER__'")

    # Use EXPLAIN to validate without executing
    explain_sql = f"EXPLAIN {test_sql}"
    try:
        response = w.statement_execution.execute_statement(
            statement=explain_sql,
            warehouse_id=SQL_WAREHOUSE_ID,
            wait_timeout="15s",
        )
        if response.status.state != StatementState.SUCCEEDED:
            error_msg = str(response.status.error) if response.status.error else "Unknown error"
            raise ValueError(
                f"SQL validation failed: {error_msg}"
            )
    except ValueError:
        raise  # Re-raise our own ValueError
    except Exception as e:
        raise ValueError(f"SQL validation failed: {e}")

    logger.info("SQL validation passed (EXPLAIN succeeded)")


def certify_entry(entry_id: str, certified_by: str, modified_sql: str = None) -> dict:
    """Certify a draft entry — moves it from draft table to certified table.

    The Vector Search index will auto-sync the new certified entry.

    Args:
        entry_id: The draft entry ID to certify.
        certified_by: Email of the certifying SME.
        modified_sql: (optional) Modified SQL to use instead of the draft's SQL.

    Returns:
        The certified entry dict.

    Raises:
        ValueError: If the draft is not found or the SQL fails validation.
    """
    w = _get_client()

    # 1. Read the draft entry
    draft = get_draft_by_id(entry_id)
    if not draft:
        raise ValueError(f"Draft entry not found: {entry_id}")

    # Use modified SQL if provided, otherwise use the draft's SQL
    final_sql = modified_sql if modified_sql else draft["parameterized_sql"]

    # 2. Validate SQL syntax before committing to certified table
    _validate_sql(w, final_sql, draft.get("parameters", []))

    # 3. Generate a new certified ID
    certified_id = f"QA-{uuid.uuid4().hex[:4].upper()}"
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    review_date = (date.today() + timedelta(days=180)).isoformat()
    params_json = json.dumps(draft.get("parameters", []))

    # Escape strings
    question_escaped = draft["question"].replace("'", "''")
    embedding_text = generate_embedding_text(draft["question"])
    embedding_text_escaped = embedding_text.replace("'", "''")
    sql_escaped = final_sql.replace("'", "''")
    template_escaped = draft["answer_template"].replace("'", "''")
    certified_by_escaped = certified_by.replace("'", "''")

    # 3. Insert into certified table
    insert_sql = f"""
    INSERT INTO {CERTIFIED_TABLE}
    (id, question, embedding_text, parameterized_sql, answer_template, parameters, status,
     certified_by, certified_date, next_review_date, created_at, updated_at)
    VALUES (
        '{certified_id}',
        '{question_escaped}',
        '{embedding_text_escaped}',
        '{sql_escaped}',
        '{template_escaped}',
        ARRAY({', '.join(f"'{p}'" for p in draft.get('parameters', []))}),
        'certified',
        '{certified_by_escaped}',
        '{now}',
        '{review_date}',
        '{now}',
        '{now}'
    )
    """
    _execute_sql(w, insert_sql)

    # 4. Delete from draft table
    delete_sql = f"DELETE FROM {DRAFT_TABLE} WHERE id = '{entry_id}'"
    _execute_sql(w, delete_sql)

    logger.info(f"Entry certified: {entry_id} -> {certified_id} by {certified_by}")

    return {
        "draft_id": entry_id,
        "certified_id": certified_id,
        "question": draft["question"],
        "certified_by": certified_by,
        "certified_date": now,
        "next_review_date": review_date,
    }


def reject_entry(entry_id: str) -> dict:
    """Reject/discard a draft entry."""
    w = _get_client()

    draft = get_draft_by_id(entry_id)
    if not draft:
        raise ValueError(f"Draft entry not found: {entry_id}")

    delete_sql = f"DELETE FROM {DRAFT_TABLE} WHERE id = '{entry_id}'"
    _execute_sql(w, delete_sql)

    logger.info(f"Draft rejected: {entry_id}")
    return {"id": entry_id, "status": "rejected"}
