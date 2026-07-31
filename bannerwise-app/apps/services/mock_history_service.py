"""Mock History Service — simulates the query history table.

Replace with real Delta table reads via Databricks SQL.
"""

from datetime import datetime, timedelta
import random


def _generate_mock_history() -> list:
    """Generate mock query history entries."""
    prompts = [
        ("What is the total ad spend for Q1 2025?", "certified", 0.93, "QA-0001"),
        ("Show me campaign performance trends", "analytical", 0.62, None),
        ("How many impressions did the holiday campaign generate?", "certified", 0.91, "QA-0012"),
        ("What is our customer acquisition cost?", "analytical", 0.44, None),
        ("What is the click-through rate by banner size?", "certified", 0.88, "QA-0023"),
        ("Predict next quarter revenue", "analytical", 0.31, None),
        ("What is the conversion rate for banner campaigns?", "certified", 0.95, "QA-0005"),
        ("Compare performance across regions", "analytical", 0.71, None),
        ("What was the ROI for the summer campaign?", "analytical", 0.78, None),
        ("Total impressions this month?", "certified", 0.89, "QA-0012"),
    ]

    history = []
    base_time = datetime.utcnow()

    for i, (prompt, lane, confidence, corpus_id) in enumerate(prompts):
        timestamp = base_time - timedelta(hours=i * 3 + random.randint(0, 2))
        history.append({
            "id": f"H-{1000 + i:04d}",
            "prompt": prompt,
            "lane": lane,
            "confidence": confidence,
            "badge": "HUMAN APPROVED" if lane == "certified" else "NOT YET APPROVED",
            "corpus_id": corpus_id,
            "user_email": "arun.wagle@databricks.com",
            "latency_ms": random.randint(400, 3500),
            "timestamp": timestamp.isoformat(),
        })

    return history


MOCK_HISTORY = _generate_mock_history()


def get_history(lane_filter: str = None, limit: int = 50) -> list:
    """Get query history, optionally filtered by lane.

    Args:
        lane_filter: Filter by lane (certified, analytical)
        limit: Max entries to return

    Returns:
        List of history entry dicts, sorted by timestamp desc.
    """
    entries = MOCK_HISTORY

    if lane_filter:
        entries = [e for e in entries if e["lane"] == lane_filter]

    return sorted(entries, key=lambda x: x["timestamp"], reverse=True)[:limit]


def get_history_stats() -> dict:
    """Get summary statistics about query history."""
    lanes = [e["lane"] for e in MOCK_HISTORY]
    confidences = [e["confidence"] for e in MOCK_HISTORY]
    return {
        "total_queries": len(MOCK_HISTORY),
        "certified_count": lanes.count("certified"),
        "analytical_count": lanes.count("analytical"),
        "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0,
        "certified_rate": round(lanes.count("certified") / len(lanes), 3) if lanes else 0,
    }
