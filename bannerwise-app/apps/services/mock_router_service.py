"""Mock Router Service — simulates the quality router agent.

Replace this with real calls to the Model Serving endpoint.
API contract is preserved so the swap is seamless.
"""

import random
import time
from datetime import datetime


# --- Mock certified corpus entries (simulates Vector Search results) ---
MOCK_CERTIFIED_ENTRIES = [
    {
        "id": "QA-0001",
        "question": "What is the total ad spend for Q1 2025?",
        "parameterized_sql": "SELECT SUM(spend) AS total_spend FROM catalog.schema.ad_metrics WHERE quarter = :quarter AND year = :year",
        "answer_template": "The total ad spend for {quarter} {year} was **${total_spend:,.2f}**.",
        "parameters": ["quarter", "year"],
        "status": "certified",
        "certified_by": "jane.smith@bannerwise.com",
        "next_review_date": "2025-09-01",
    },
    {
        "id": "QA-0012",
        "question": "How many impressions did the holiday campaign generate?",
        "parameterized_sql": "SELECT SUM(impressions) AS total_impressions FROM catalog.schema.campaign_metrics WHERE campaign_name = :campaign_name",
        "answer_template": "The {campaign_name} campaign generated **{total_impressions:,}** total impressions.",
        "parameters": ["campaign_name"],
        "status": "certified",
        "certified_by": "mike.chen@bannerwise.com",
        "next_review_date": "2025-08-15",
    },
    {
        "id": "QA-0023",
        "question": "What is the click-through rate by banner size?",
        "parameterized_sql": "SELECT banner_size, AVG(ctr) AS avg_ctr FROM catalog.schema.banner_performance GROUP BY banner_size ORDER BY avg_ctr DESC",
        "answer_template": "Click-through rates by banner size:\n{results_table}",
        "parameters": [],
        "status": "certified",
        "certified_by": "sarah.jones@bannerwise.com",
        "next_review_date": "2025-10-01",
    },
]


def assess_prompt(prompt: str) -> dict:
    """Assess a user prompt through the confidence gate.

    Args:
        prompt: The user's natural language question.

    Returns:
        RouterResult dict with badge, confidence, lane, answer, and provenance.
    """
    start_time = time.time()

    # Simulate retrieval + reranking latency
    time.sleep(random.uniform(0.3, 0.8))

    # Mock confidence scoring — randomly choose lane for demo
    confidence = random.uniform(0.45, 0.98)
    threshold = 0.85

    if confidence >= threshold:
        # --- Certified Lane ---
        entry = random.choice(MOCK_CERTIFIED_ENTRIES)
        latency_ms = int((time.time() - start_time) * 1000)

        return {
            "answer": _render_mock_answer(entry),
            "badge": "HUMAN APPROVED",
            "confidence": round(confidence, 3),
            "lane": "certified",
            "provenance": {
                "corpus_id": entry["id"],
                "certified_by": entry["certified_by"],
                "next_review_date": entry["next_review_date"],
                "sql_executed": entry["parameterized_sql"],
                "parameters_extracted": entry["parameters"],
                "latency_ms": latency_ms,
                "timestamp": datetime.utcnow().isoformat(),
                "raw_score": round(confidence + random.uniform(0.01, 0.05), 3),
                "calibrated_score": round(confidence, 3),
            },
        }
    else:
        # --- Analytical Lane ---
        latency_ms = int((time.time() - start_time) * 1000) + random.randint(800, 2000)

        return {
            "answer": _generate_mock_genie_answer(prompt),
            "badge": "NOT YET APPROVED",
            "confidence": round(confidence, 3),
            "lane": "analytical",
            "provenance": {
                "source": "Genie Space (Conversation API)",
                "genie_space_id": "genie-space-mock-001",
                "genie_sql": f"SELECT * FROM catalog.schema.metrics WHERE question LIKE '%{prompt[:20]}%' LIMIT 100",
                "confidence_reason": f"Below threshold ({confidence:.2f} < {threshold})",
                "latency_ms": latency_ms,
                "timestamp": datetime.utcnow().isoformat(),
            },
        }


def _render_mock_answer(entry: dict) -> str:
    """Simulate rendering an answer from a certified template."""
    mock_answers = {
        "QA-0001": "The total ad spend for Q1 2025 was **$2,847,392.50**.",
        "QA-0012": "The Holiday 2024 campaign generated **14,283,901** total impressions.",
        "QA-0023": "Click-through rates by banner size:\n| Size | CTR |\n|------|-----|\n| 300x250 | 2.4% |\n| 728x90 | 1.8% |\n| 160x600 | 1.2% |",
    }
    return mock_answers.get(entry["id"], entry["answer_template"])


def _generate_mock_genie_answer(prompt: str) -> str:
    """Simulate a Genie Space analytical response."""
    return (
        f"Based on the available data, here is what I found for your question: "
        f"\"{prompt}\"\n\n"
        f"The analysis shows a 12.3% increase compared to the previous period, "
        f"with the primary driver being increased engagement in the 25-34 demographic segment. "
        f"This answer was generated by Genie Agent and has not been certified by an SME."
    )
