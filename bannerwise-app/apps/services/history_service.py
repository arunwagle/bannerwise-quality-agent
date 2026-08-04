"""History Service — reads query history from the Delta table."""

import os
import logging
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

logger = logging.getLogger(__name__)

CATALOG = os.environ.get("CATALOG_NAME", "aw_serverless_stable_catalog")
SCHEMA = os.environ.get("SCHEMA_NAME", "bannerhealth")
SQL_WAREHOUSE_ID = os.environ.get("SQL_WAREHOUSE_ID", "2d8e531640ffa469")
HISTORY_TABLE = f"{CATALOG}.{SCHEMA}.query_history"



def _get_client():
    return WorkspaceClient()


def _execute_sql(w, sql: str) -> list:
    """Execute SQL and return list of row dicts."""
    response = w.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=SQL_WAREHOUSE_ID,
        wait_timeout="30s",
    )
    if response.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"SQL failed: {response.status.error}")
    if not response.result or not response.result.data_array:
        return []
    columns = [col.name for col in response.manifest.schema.columns]
    return [dict(zip(columns, row)) for row in response.result.data_array]


def get_history(lane_filter: str = None, limit: int = 50) -> list:
    """Get query history entries from the Delta table."""
    w = _get_client()
    where = f"WHERE lane = '{lane_filter}'" if lane_filter else ""
    sql = f"""
    SELECT id, user_email, prompt, lane, confidence, badge,
           corpus_id, sql_executed, answer, latency_ms, timestamp
    FROM {HISTORY_TABLE}
    {where}
    ORDER BY timestamp DESC
    LIMIT {limit}
    """
    return _execute_sql(w, sql)


def get_history_stats() -> dict:
    """Get summary statistics about query history."""
    w = _get_client()
    sql = f"""
    SELECT
        COALESCE(COUNT(*), 0) as total_queries,
        COALESCE(SUM(CASE WHEN lane = 'certified' THEN 1 ELSE 0 END), 0) as certified_count,
        COALESCE(SUM(CASE WHEN lane = 'analytical' THEN 1 ELSE 0 END), 0) as analytical_count,
        COALESCE(ROUND(AVG(confidence), 3), 0) as avg_confidence
    FROM {HISTORY_TABLE}
    """
    rows = _execute_sql(w, sql)
    if rows:
        return rows[0]
    return {"total_queries": 0, "certified_count": 0, "analytical_count": 0, "avg_confidence": 0}


def log_query(entry: dict) -> None:
    """Log a query to the history table after it's been processed."""
    w = _get_client()
    import uuid
    from datetime import datetime

    entry_id = f"H-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    # Escape strings
    prompt = (entry.get("prompt") or "").replace("'", "''")
    lane = (entry.get("lane") or "analytical").replace("'", "''")
    badge = (entry.get("badge") or "").replace("'", "''")
    corpus_id = entry.get("corpus_id") or None
    sql_executed = (entry.get("sql_executed") or "").replace("'", "''")
    answer = (entry.get("answer") or "").replace("'", "''")
    user_email = (entry.get("user_email") or "app_user").replace("'", "''")
    confidence = entry.get("confidence", 0.0) or 0.0
    latency_ms = entry.get("latency_ms", 0) or 0

    corpus_val = f"'{corpus_id}'" if corpus_id else "NULL"

    sql = f"""
    INSERT INTO {HISTORY_TABLE}
    (id, user_email, prompt, lane, confidence, badge, corpus_id, sql_executed, answer, latency_ms, timestamp)
    VALUES (
        '{entry_id}', '{user_email}', '{prompt}', '{lane}',
        {confidence}, '{badge}', {corpus_val},
        '{sql_executed}', '{answer}', {latency_ms}, '{now}'
    )
    """
    try:
        _execute_sql(w, sql)
        logger.info(f"Logged query {entry_id} to history")
    except Exception as e:
        logger.error(f"Failed to log query to history: {e}")
