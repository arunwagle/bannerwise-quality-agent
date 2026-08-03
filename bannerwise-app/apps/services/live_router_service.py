"""Live Router Service — calls the Model Serving endpoint.

Uses Databricks SDK for authentication (auto-configures in Apps runtime).
Same interface as mock_router_service: assess_prompt(prompt) → dict
"""

import os
import time
import logging
from databricks.sdk import WorkspaceClient

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

        # Extract fields
        if isinstance(prediction, dict):
            lane = prediction.get("lane", "analytical")
            confidence = prediction.get("confidence", 0.0)
            corpus_id = prediction.get("corpus_id")
            matched_question = prediction.get("matched_question")
            vs_score = prediction.get("vs_score", 0.0)
            judge_verdict = prediction.get("judge_verdict", "UNKNOWN")
            reason = prediction.get("reason", "")
            threshold_used = prediction.get("threshold_used", 0.5)
            candidates_evaluated = prediction.get("candidates_evaluated", 0)
            error = prediction.get("error")
        else:
            lane = "analytical"
            confidence = 0.0
            corpus_id = None
            matched_question = None
            vs_score = 0.0
            judge_verdict = "UNKNOWN"
            reason = f"Unexpected response format: {type(prediction)}"
            threshold_used = 0.5
            candidates_evaluated = 0
            error = reason

        if lane == "certified":
            return {
                "answer": f"[Certified Answer] Matched: {matched_question}",
                "badge": "HUMAN APPROVED",
                "confidence": round(confidence, 3),
                "lane": "certified",
                "provenance": {
                    "corpus_id": corpus_id,
                    "matched_question": matched_question,
                    "vs_score": vs_score,
                    "judge_verdict": judge_verdict,
                    "reason": reason,
                    "threshold_used": threshold_used,
                    "candidates_evaluated": candidates_evaluated,
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
                    "vs_score": vs_score,
                    "judge_verdict": judge_verdict,
                    "reason": reason,
                    "threshold_used": threshold_used,
                    "candidates_evaluated": candidates_evaluated,
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
            "provenance": {
                "error": str(e),
                "endpoint": ENDPOINT_NAME,
                "reason": f"Endpoint error: {str(e)[:100]}",
            },
            "latency_ms": latency_ms,
        }
