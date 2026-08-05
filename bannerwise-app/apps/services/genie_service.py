"""Genie Space Service — queries the Genie Space API for analytical answers.

Includes an LLM-based SQL correction step that validates and fixes common
issues in Genie-generated SQL (unquoted strings, missing aliases, etc.)
before returning results to the user or the draft table.
"""

import os
import re
import time
import logging
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

logger = logging.getLogger(__name__)

GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "")
LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct")
MAX_POLL_SECONDS = 60
POLL_INTERVAL = 2


def _get_client():
    return WorkspaceClient()


def query_genie_space(prompt: str) -> dict:
    """Send a question to the Genie Space and return the answer.

    Args:
        prompt: The user's natural language question.

    Returns:
        dict with keys:
            - answer: str or None (the formatted result)
            - sql_executed: str or None (the SQL Genie generated)
            - status: str ("success", "failed", "timeout", "not_configured")
            - error: str or None
    """
    if not GENIE_SPACE_ID:
        return {
            "answer": None,
            "sql_executed": None,
            "status": "not_configured",
            "error": "GENIE_SPACE_ID environment variable not set",
        }

    w = _get_client()

    try:
        # Start a conversation
        start_resp = w.api_client.do(
            "POST",
            f"/api/2.0/genie/spaces/{GENIE_SPACE_ID}/start-conversation",
            body={"content": prompt},
        )

        conversation_id = start_resp["conversation_id"]
        message_id = start_resp["message_id"]

        # Poll for completion
        elapsed = 0
        while elapsed < MAX_POLL_SECONDS:
            msg_resp = w.api_client.do(
                "GET",
                f"/api/2.0/genie/spaces/{GENIE_SPACE_ID}/conversations/{conversation_id}/messages/{message_id}",
            )

            status = msg_resp.get("status", "UNKNOWN")

            if status == "COMPLETED":
                return _extract_result(msg_resp)
            elif status in ("FAILED", "CANCELLED"):
                error_msg = msg_resp.get("error", {}).get("message", "Unknown error")
                return {
                    "answer": None,
                    "sql_executed": None,
                    "status": "failed",
                    "error": f"Genie query failed: {error_msg}",
                }

            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

        return {
            "answer": None,
            "sql_executed": None,
            "status": "timeout",
            "error": f"Genie query timed out after {MAX_POLL_SECONDS}s",
        }

    except Exception as e:
        logger.error(f"Genie Space API error: {e}")
        return {
            "answer": None,
            "sql_executed": None,
            "status": "failed",
            "error": str(e),
        }


def _extract_result(msg_resp: dict) -> dict:
    """Extract SQL and answer from a completed Genie message response."""
    sql_executed = None
    answer = None

    attachments = msg_resp.get("attachments", [])

    for attachment in attachments:
        # Extract SQL query
        if attachment.get("query") and attachment["query"].get("query"):
            sql_executed = attachment["query"]["query"]

        # Extract text content
        if attachment.get("text") and attachment["text"].get("content"):
            answer = attachment["text"]["content"]

    # --- LLM SQL Correction ---
    # Validate and fix common issues before returning
    if sql_executed:
        sql_executed = correct_sql(sql_executed)

    # If no text answer but we have SQL, indicate SQL was executed
    if not answer and sql_executed:
        answer = f"Query executed successfully. SQL: {sql_executed[:200]}"

    # Check for description in the message itself
    if not answer:
        answer = msg_resp.get("content", None)

    return {
        "answer": answer,
        "sql_executed": sql_executed,
        "status": "success",
        "error": None,
    }


def correct_sql(sql: str) -> str:
    """Validate and correct common SQL issues from Genie-generated queries.

    Uses fast regex-based fixes for known patterns first (no LLM needed),
    then falls back to LLM for complex issues.
    """
    corrected = _regex_fix_unquoted_strings(sql)
    if corrected != sql:
        logger.info("SQL corrected by regex (fixed unquoted string literals)")
        return corrected
    # If regex didn't find anything, try LLM as fallback
    return _llm_correct_sql(sql)


def _regex_fix_unquoted_strings(sql: str) -> str:
    """Fast regex-based fix for unquoted string literals in SQL.

    Detects: WHERE column = Q2 2025 AND ...
    Fixes:   WHERE column = 'Q2 2025' AND ...
    """
    stop_words = r'(?:AND|OR|IS|NOT|NULL|IN|BETWEEN|EXISTS|LIKE|GROUP|ORDER|LIMIT|HAVING|ON|JOIN|WHERE|SET|FROM|INTO|SELECT|UNION|CASE|WHEN|THEN|ELSE|END|AS|TRUE|FALSE)'

    pattern = (
        r"((?:=|!=|<>)\s+)"
        r"(?!')"
        r"([A-Za-z][A-Za-z0-9]*"
        r"(?:\s+(?!" + stop_words + r"\b)[A-Za-z0-9]+)*"
        r")"
        r"(?=\s+" + stop_words + r"\b|\s*[);,]|\s*$)"
    )

    def replace_match(match):
        operator = match.group(1)
        value = match.group(2).strip()
        if ' ' not in value:
            return match.group(0)
        return f"{operator}'{value}'"

    return re.sub(pattern, replace_match, sql, flags=re.IGNORECASE | re.MULTILINE)


def _llm_correct_sql(sql: str) -> str:
    """Fallback: use LLM to fix SQL issues not caught by regex."""
    w = _get_client()

    correction_prompt = f"""You are a Databricks SQL syntax validator. Review the following SQL query and fix ONLY syntax errors. Do NOT change the query logic, table names, column names, or add new clauses.

Common issues to fix:
1. Unquoted string literals in WHERE clauses (e.g., WHERE period = Q2 2025 should be WHERE period = 'Q2 2025')
2. Unquoted string values in comparisons
3. Missing single quotes around date/text values

Rules:
- Return ONLY the corrected SQL, nothing else
- Do NOT add comments, explanations, or markdown formatting
- Do NOT change table names, column names, aliases, or query structure
- Do NOT add LIMIT, ORDER BY, or any new clauses
- If the SQL is already correct, return it unchanged

SQL to validate:
{sql}

Corrected SQL:"""

    try:
        response = w.serving_endpoints.query(
            name=LLM_ENDPOINT,
            messages=[ChatMessage(role=ChatMessageRole.USER, content=correction_prompt)],
            temperature=0.0,
            max_tokens=2000,
        )
        corrected = response.choices[0].message.content.strip()

        # Remove markdown code fences if LLM wraps the response
        if corrected.startswith("```"):
            lines = corrected.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            corrected = "\n".join(lines).strip()

        # Sanity check: corrected SQL should still be a SELECT/WITH statement
        corrected_upper = corrected.upper().lstrip()
        if corrected_upper.startswith("SELECT") or corrected_upper.startswith("WITH"):
            if corrected != sql:
                logger.info("SQL corrected by LLM (original had issues)")
            return corrected
        else:
            logger.warning("LLM SQL correction returned non-SQL output, keeping original")
            return sql

    except Exception as e:
        logger.warning(f"SQL correction LLM call failed (using original): {e}")
        return sql
