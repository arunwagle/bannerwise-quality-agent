"""Live Router Service — calls the Model Serving endpoint.

Replaces mock_router_service when API_MODE='live'.
Same interface: assess_prompt(prompt) → dict
"""

import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

# Configuration from environment
ENDPOINT_NAME = os.environ.get("SERVING_ENDPOINT_NAME", "bannerwise-quality-router")
DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "")
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN", "")


def _get_endpoint_url():
    """Build the serving endpoint invocation URL."""
    host = DATABRICKS_HOST.rstrip("/")
    if not host.startswith("http"):
        host = f"https://{host}"
    return f"{host}/serving-endpoints/{ENDPOINT_NAME}/invocations"


def assess_prompt(prompt: str) -> dict:
    """Assess a user prompt through the live Model Serving endpoint.

    Args:
        prompt: The user's natural language question.

    Returns:
        RouterResult dict with badge, confidence, lane, answer, and provenance.
    """
    start_time = time.time()
    url = _get_endpoint_url()
    headers = {
        "Authorization": f"Bearer {DATABRICKS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "dataframe_records": [{"prompt": prompt}]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        latency_ms = int((time.time() - start_time) * 1000)

        # Parse model response
        prediction = result.get("predictions", [{}])[0]
        lane = prediction.get("lane", "analytical")
        confidence = prediction.get("confidence", 0.0)
        corpus_id = prediction.get("corpus_id")
        matched_question = prediction.get("matched_question")
        error = prediction.get("error")

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
                    "reason": "Below confidence threshold or no match",
                    "endpoint": ENDPOINT_NAME,
                },
                "latency_ms": latency_ms,
            }

    except requests.exceptions.Timeout:
        logger.error(f"Serving endpoint timeout: {url}")
        return {
            "answer": None,
            "badge": "ERROR",
            "confidence": 0.0,
            "lane": "error",
            "provenance": {"error": "Endpoint timeout (30s)"},
            "latency_ms": int((time.time() - start_time) * 1000),
        }
    except requests.exceptions.HTTPError as e:
        logger.error(f"Serving endpoint error: {e.response.status_code} - {e.response.text[:200]}")
        return {
            "answer": None,
            "badge": "ERROR",
            "confidence": 0.0,
            "lane": "error",
            "provenance": {"error": f"HTTP {e.response.status_code}: {e.response.text[:100]}"},
            "latency_ms": int((time.time() - start_time) * 1000),
        }
    except Exception as e:
        logger.error(f"Serving endpoint exception: {e}")
        return {
            "answer": None,
            "badge": "ERROR",
            "confidence": 0.0,
            "lane": "error",
            "provenance": {"error": str(e)},
            "latency_ms": int((time.time() - start_time) * 1000),
        }
