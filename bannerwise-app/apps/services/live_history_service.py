"""Live History Service — reads query history from Delta table."""

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
        COUNT(*) as total,
        SUM(CASE WHEN lane = 'certified' THEN 1 ELSE 0 END) as certified,
        SUM(CASE WHEN lane = 'analytical' THEN 1 ELSE 0 END) as analytical,
        AVG(latency_ms) as avg_latency_ms
    FROM {HISTORY_TABLE}
    """
    rows = _execute_sql(w, sql)
    if rows:
        return rows[0]
    return {"total": 0, "certified": 0, "analytical": 0, "avg_latency_ms": 0}
