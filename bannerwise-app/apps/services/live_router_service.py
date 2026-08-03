"""Live Router Service — calls the Model Serving endpoint.

Uses Databricks SDK for authentication (auto-configures in Apps runtime).
Same interface as mock_router_service: assess_prompt(prompt) → dict
"""

import os
import time
import logging
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import DataframeSplitInput

logger = logging.getLogger(__name__)

ENDPOINT_NAME = os.environ.get("SERVING_ENDPOINT_NAME", "bannerwise-quality-router")


def _get_client():
    """Get authenticated WorkspaceClient (auto-configures in Apps runtime)."""
    return WorkspaceClient()


def assess_prompt(prompt: str) -> dict:
    """Assess a user prompt through the live Model Serving endpoint.

    Args:
        prompt: The user's natural language question.

    Returns:
        RouterResult dict with badge, confidence, lane, answer, and provenance.
    """
    start_time = time.time()

    try:
        w = _get_client()

        # Use SDK to call serving endpoint (handles auth automatically)
        response = w.serving_endpoints.query(
            name=ENDPOINT_NAME,
            dataframe_records=[{"prompt": prompt}],
        )

        latency_ms = int((time.time() - start_time) * 1000)

        # Parse model response
        predictions = response.predictions
        if isinstance(predictions, list) and len(predictions) > 0:
            prediction = predictions[0]
        elif isinstance(predictions, dict):
            prediction = predictions
        else:
            prediction = {}

        # Handle both dict and list-of-dicts response formats
        if isinstance(prediction, dict):
            lane = prediction.get("lane", "analytical")
            confidence = prediction.get("confidence", 0.0)
            corpus_id = prediction.get("corpus_id")
            matched_question = prediction.get("matched_question")
            error = prediction.get("error")
        else:
            lane = "analytical"
            confidence = 0.0
            corpus_id = None
            matched_question = None
            error = f"Unexpected response format: {type(prediction)}"

        if lane == "certified":
            return {
                "answer": f"[Certified Answer] Matched: {matched_question}",
                "badge": "HUMAN APPROVED",
                "confidence": round(confidence, 3),
                "lane": "certified",
                "provenance": {
                    "corpus_id": corpus_id,
                    "matched_question": matched_question,
                    "endpoint": ENDPOINT_NAME,
                },
                "latency_ms": latency_ms,
            }
        else:
            return {
                "answer": None,
                "badge": "NOT YET APPROVED",
                "confidence": round(confidence, 3),
                "lane": "analytical",
                "provenance": {
                    "corpus_id": corpus_id,
                    "matched_question": matched_question,
                    "reason": error or "Below confidence threshold or no match",
                    "endpoint": ENDPOINT_NAME,
                },
                "latency_ms": latency_ms,
            }

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Serving endpoint error: {e}")
        return {
            "answer": None,
            "badge": "ERROR",
            "confidence": 0.0,
            "lane": "error",
            "provenance": {"error": str(e), "endpoint": ENDPOINT_NAME},
            "latency_ms": latency_ms,
        }
