"""Live Router Service — calls the Model Serving endpoint.

Uses Databricks SDK for authentication (auto-configures in Apps runtime).
Same interface as demo_router_service: assess_prompt(prompt) → dict
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

        # Extract fields — corpus_id and other routing details are nested
        # inside "provenance" in the RouterResult.to_dict() output
        if isinstance(prediction, dict):
            lane = prediction.get("lane", "analytical")
            confidence = prediction.get("confidence", 0.0)
            provenance = prediction.get("provenance", {})

            # Certified lane: provenance.corpus_id
            # Analytical lane: provenance.best_candidate.corpus_id
            best_candidate = provenance.get("best_candidate", {})
            corpus_id = (
                provenance.get("corpus_id")
                or best_candidate.get("corpus_id")
                or prediction.get("corpus_id")
            )
            matched_question = (
                provenance.get("certified_question")
                or best_candidate.get("question")
                or prediction.get("matched_question")
            )
            vs_score = (
                best_candidate.get("vs_score")
                or provenance.get("vs_score")
                or prediction.get("vs_score", 0.0)
            )
            judge_verdict = provenance.get("judge_verdict", prediction.get("judge_verdict", "UNKNOWN"))
            reason = provenance.get("reason", prediction.get("reason", ""))
            threshold_used = provenance.get("threshold_used", prediction.get("threshold_used", 0.5))
            candidates_evaluated = provenance.get("candidates_evaluated", prediction.get("candidates_evaluated", 0))
            error = prediction.get("error") or provenance.get("error")
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
            # Execute Certified Lane: lookup SQL, extract params, execute, format answer
            from services.certified_lane_service import execute_certified_lane

            certified_result = execute_certified_lane(
                prompt=prompt,
                corpus_id=corpus_id,
                matched_question=matched_question,
            )

            total_latency = latency_ms + certified_result.get("latency_ms", 0)

            return {
                "answer": certified_result["answer"],
                "badge": "Certified",
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
                    "sql_executed": certified_result.get("sql_executed"),
                    "params_extracted": certified_result.get("params_extracted"),
                    "answer_template": certified_result.get("answer_template"),
                },
                "latency_ms": total_latency,
            }
        else:
            # Analytical Lane: forward to Genie Space for dynamic answer
            from services.genie_service import query_genie_space

            genie_result = query_genie_space(prompt)

            return {
                "answer": genie_result.get("answer"),
                "badge": "Not Certified",
                "confidence": round(confidence, 3),
                "lane": "analytical",
                "sql_executed": genie_result.get("sql_executed"),
                "provenance": {
                    "source": "genie_space",
                    "genie_status": genie_result.get("status"),
                    "sql_executed": genie_result.get("sql_executed"),
                    "genie_error": genie_result.get("error"),
                    "corpus_id": corpus_id,
                    "matched_question": matched_question,
                    "vs_score": vs_score,
                    "judge_verdict": judge_verdict,
                    "reason": reason,
                    "threshold_used": threshold_used,
                    "candidates_evaluated": candidates_evaluated,
                    "endpoint": ENDPOINT_NAME,
                },
                "latency_ms": int((time.time() - start_time) * 1000),
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
