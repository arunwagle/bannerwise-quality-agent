"""Certified Lane Service — Executes pre-approved SQL and formats answers.

When the router routes a prompt to the Certified Lane (State 1), this service:
1. Looks up the corpus entry by corpus_id
2. Extracts parameters from the user prompt via LLM
3. Binds parameters into the pre-approved SQL
4. Executes the SQL via Databricks SQL Warehouse
5. Formats the result using the stored answer template
6. Returns the actual data answer with full provenance
"""

import os
import json
import time
import re
import logging
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

logger = logging.getLogger(__name__)

# Configuration
CATALOG = os.environ.get("CATALOG_NAME", "aw_serverless_stable_catalog")
SCHEMA = os.environ.get("SCHEMA_NAME", "bannerhealth")
SQL_WAREHOUSE_ID = os.environ.get("SQL_WAREHOUSE_ID", "2d8e531640ffa469")
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct")
CORPUS_TABLE = f"{CATALOG}.{SCHEMA}.certified_qa_corpus"


def _get_client():
    """Get authenticated WorkspaceClient."""
    return WorkspaceClient()


def _lookup_corpus_entry(w, corpus_id: str) -> dict:
    """Fetch the corpus entry (SQL template, answer template, parameters) from Delta table.

    Uses the SQL Statement Execution API to query the corpus table.
    """
    lookup_sql = f"""
    SELECT parameterized_sql, answer_template, parameters, question
    FROM {CORPUS_TABLE}
    WHERE id = '{corpus_id}' AND status = 'certified'
    LIMIT 1
    """

    response = w.statement_execution.execute_statement(
        statement=lookup_sql,
        warehouse_id=SQL_WAREHOUSE_ID,
        wait_timeout="30s",
    )

    if response.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"Corpus lookup failed: {response.status.error}")

    if not response.result or not response.result.data_array:
        raise ValueError(f"Corpus entry not found: {corpus_id}")

    row = response.result.data_array[0]
    columns = [col.name for col in response.manifest.schema.columns]
    entry = dict(zip(columns, row))

    # Parse parameters list (stored as JSON array string in Delta)
    params_raw = entry.get("parameters", "[]")
    if isinstance(params_raw, str):
        try:
            entry["parameters"] = json.loads(params_raw)
        except json.JSONDecodeError:
            entry["parameters"] = []

    return entry


def _extract_parameters(w, prompt: str, parameters: list, matched_question: str) -> dict:
    """Extract parameter values from the user's prompt using an LLM.

    Given the template question (with {param} placeholders) and the user's prompt,
    asks the LLM to identify what concrete values the user provided for each parameter.
    """
    if not parameters:
        return {}

    param_list = ", ".join(parameters)

    extraction_prompt = f"""Extract the parameter values from the user's question.

The certified question template is: "{matched_question}"
The parameters to extract are: [{param_list}]
The user's actual question is: "{prompt}"

For each parameter, identify the concrete value the user provided.
Return ONLY a JSON object mapping parameter names to their values.
If a parameter cannot be determined, use "unknown".

Example:
Template: "What is the total ad spend for {{period}}?"
User: "What is the total ad spend for Q1 2025?"
Output: {{"period": "Q1 2025"}}

Return ONLY the JSON object, no explanation."""

    import requests
    host = os.environ.get("DATABRICKS_HOST", "")
    if not host:
        # Get from SDK config
        host = w.config.host

    # Use SDK's authenticate() method — works in all environments (Apps, notebooks, local)
    headers = w.config.authenticate()
    headers["Content-Type"] = "application/json"

    resp = requests.post(
        f"{host}/serving-endpoints/{LLM_ENDPOINT}/invocations",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": extraction_prompt}],
            "temperature": 0.0,
            "max_tokens": 200,
        },
        timeout=30,
    )
    resp.raise_for_status()
    llm_response = resp.json()["choices"][0]["message"]["content"].strip()

    # Parse JSON from LLM response
    try:
        # Handle potential markdown code block wrapping
        if "```" in llm_response:
            json_match = re.search(r'```(?:json)?\s*(.+?)\s*```', llm_response, re.DOTALL)
            if json_match:
                llm_response = json_match.group(1)
        return json.loads(llm_response)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM param extraction: {llm_response}")
        return {p: "unknown" for p in parameters}


def _bind_sql(parameterized_sql: str, params: dict) -> str:
    """Bind extracted parameters into the SQL template.

    Replaces :param_name placeholders with quoted values.
    """
    bound_sql = parameterized_sql
    for param_name, param_value in params.items():
        # Replace :param_name with quoted value (safe string substitution)
        # Handle both :param and :param_name patterns
        bound_sql = re.sub(
            rf':{param_name}\b',
            f"'{param_value}'",
            bound_sql
        )
    return bound_sql


def _execute_sql(w, sql: str) -> list:
    """Execute the bound SQL against the warehouse and return results.

    Returns a list of dicts (one per row).
    """
    response = w.statement_execution.execute_statement(
        statement=sql,
        warehouse_id=SQL_WAREHOUSE_ID,
        catalog=CATALOG,
        schema=SCHEMA,
        wait_timeout="30s",
    )

    if response.status.state != StatementState.SUCCEEDED:
        error_msg = response.status.error.message if response.status.error else "Unknown error"
        raise RuntimeError(f"SQL execution failed: {error_msg}")

    if not response.result or not response.result.data_array:
        return []

    columns = [col.name for col in response.manifest.schema.columns]
    rows = []
    for row_data in response.result.data_array:
        rows.append(dict(zip(columns, row_data)))

    return rows


def _format_answer(answer_template: str, params: dict, sql_results: list) -> str:
    """Format the answer using the template, parameters, and SQL results.

    The template can reference:
    - Parameter values: {period}, {campaign}, etc.
    - SQL result columns: {total_spend}, {impressions}, etc. (with optional format specs)
    """
    if not sql_results:
        return f"No data found for the given parameters: {params}"

    # Merge params + first row of results into a single context dict
    context = dict(params)
    first_row = sql_results[0]
    for col, val in first_row.items():
        # Try to convert numeric strings
        try:
            context[col] = float(val)
        except (ValueError, TypeError):
            context[col] = val

    # Format the template with the context
    try:
        formatted = answer_template.format(**context)
    except (KeyError, ValueError) as e:
        # Fallback: show raw results if template fails
        logger.warning(f"Template formatting failed: {e}")
        formatted = f"Result: {first_row}"

    return formatted


def execute_certified_lane(prompt: str, corpus_id: str, matched_question: str) -> dict:
    """Execute the full Certified Lane flow.

    Args:
        prompt: The user's original question
        corpus_id: The matched corpus entry ID (e.g., "QA-0001")
        matched_question: The matched certified question template

    Returns:
        Dict with 'answer', 'sql_executed', 'params_extracted', 'raw_results'
    """
    start_time = time.time()

    try:
        w = _get_client()

        # Step 1: Lookup corpus entry
        entry = _lookup_corpus_entry(w, corpus_id)
        parameterized_sql = entry["parameterized_sql"]
        answer_template = entry["answer_template"]
        parameters = entry["parameters"]

        # Step 2: Extract parameters from user prompt
        params = _extract_parameters(w, prompt, parameters, matched_question)
        logger.info(f"Extracted params: {params}")

        # Step 3: Bind parameters into SQL
        bound_sql = _bind_sql(parameterized_sql, params)
        logger.info(f"Bound SQL: {bound_sql}")

        # Step 4: Execute SQL
        results = _execute_sql(w, bound_sql)

        # Step 5: Format answer
        answer = _format_answer(answer_template, params, results)

        latency_ms = int((time.time() - start_time) * 1000)

        return {
            "answer": answer,
            "sql_executed": bound_sql,
            "params_extracted": params,
            "raw_results": results,
            "answer_template": answer_template,
            "latency_ms": latency_ms,
            "error": None,
        }

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Certified lane execution failed: {e}")
        return {
            "answer": f"[Certified Match] {matched_question} (SQL execution failed: {str(e)[:100]})",
            "sql_executed": None,
            "params_extracted": None,
            "raw_results": None,
            "answer_template": None,
            "latency_ms": latency_ms,
            "error": str(e),
        }
