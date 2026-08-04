"""Genie Space Service — queries the Genie Space API for analytical answers."""

import os
import time
import logging
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

GENIE_SPACE_ID = os.environ.get("GENIE_SPACE_ID", "")
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
