"""Mock Corpus Service — simulates reading the certified QA corpus Delta table.

Replace with real Databricks SQL or SDK calls to the corpus table.
"""

from datetime import date, datetime


MOCK_CORPUS = [
    {
        "id": "QA-0001",
        "question": "What is the total ad spend for Q1 2025?",
        "status": "certified",
        "certified_by": "jane.smith@bannerwise.com",
        "certified_date": "2025-01-15",
        "next_review_date": "2025-09-01",
        "parameterized_sql": "SELECT SUM(spend) AS total_spend FROM catalog.schema.ad_metrics WHERE quarter = :quarter AND year = :year",
        "answer_template": "The total ad spend for {quarter} {year} was **${total_spend:,.2f}**.",
        "parameters": ["quarter", "year"],
        "updated_at": "2025-01-15T10:30:00",
    },
    {
        "id": "QA-0005",
        "question": "What is the conversion rate for banner campaigns?",
        "status": "certified",
        "certified_by": "mike.chen@bannerwise.com",
        "certified_date": "2025-02-01",
        "next_review_date": "2025-08-01",
        "parameterized_sql": "SELECT campaign_id, conversions / clicks AS conversion_rate FROM catalog.schema.campaign_metrics WHERE campaign_type = 'banner'",
        "answer_template": "The conversion rate for banner campaigns is **{conversion_rate:.1%}**.",
        "parameters": [],
        "updated_at": "2025-02-01T14:20:00",
    },
    {
        "id": "QA-0012",
        "question": "How many impressions did the holiday campaign generate?",
        "status": "certified",
        "certified_by": "mike.chen@bannerwise.com",
        "certified_date": "2025-01-20",
        "next_review_date": "2025-08-15",
        "parameterized_sql": "SELECT SUM(impressions) AS total_impressions FROM catalog.schema.campaign_metrics WHERE campaign_name = :campaign_name",
        "answer_template": "The {campaign_name} campaign generated **{total_impressions:,}** total impressions.",
        "parameters": ["campaign_name"],
        "updated_at": "2025-01-20T09:15:00",
    },
    {
        "id": "QA-0018",
        "question": "Which regions have the highest CPM?",
        "status": "draft",
        "certified_by": None,
        "certified_date": None,
        "next_review_date": "2025-07-01",
        "parameterized_sql": "SELECT region, AVG(cpm) AS avg_cpm FROM catalog.schema.regional_metrics GROUP BY region ORDER BY avg_cpm DESC LIMIT 10",
        "answer_template": "Top regions by CPM:\n{results_table}",
        "parameters": [],
        "updated_at": "2025-03-10T16:45:00",
    },
    {
        "id": "QA-0023",
        "question": "What is the click-through rate by banner size?",
        "status": "certified",
        "certified_by": "sarah.jones@bannerwise.com",
        "certified_date": "2025-02-10",
        "next_review_date": "2025-10-01",
        "parameterized_sql": "SELECT banner_size, AVG(ctr) AS avg_ctr FROM catalog.schema.banner_performance GROUP BY banner_size ORDER BY avg_ctr DESC",
        "answer_template": "Click-through rates by banner size:\n{results_table}",
        "parameters": [],
        "updated_at": "2025-02-10T11:00:00",
    },
    {
        "id": "QA-0031",
        "question": "What was the ROI for the summer campaign?",
        "status": "expired",
        "certified_by": "jane.smith@bannerwise.com",
        "certified_date": "2024-09-01",
        "next_review_date": "2025-03-01",
        "parameterized_sql": "SELECT (revenue - spend) / spend AS roi FROM catalog.schema.campaign_metrics WHERE campaign_name = :campaign_name",
        "answer_template": "The ROI for {campaign_name} was **{roi:.1%}**.",
        "parameters": ["campaign_name"],
        "updated_at": "2024-09-01T08:30:00",
    },
]


def get_all_entries(status_filter: str = None, search: str = None) -> list:
    """Get all corpus entries, optionally filtered.

    Args:
        status_filter: Filter by status (certified, draft, expired)
        search: Search query against question text

    Returns:
        List of corpus entry dicts.
    """
    entries = MOCK_CORPUS

    if status_filter:
        entries = [e for e in entries if e["status"] == status_filter]

    if search:
        search_lower = search.lower()
        entries = [e for e in entries if search_lower in e["question"].lower()]

    return entries


def get_entry_by_id(entry_id: str) -> dict:
    """Get a single corpus entry by ID."""
    for entry in MOCK_CORPUS:
        if entry["id"] == entry_id:
            return entry
    return None


def get_corpus_stats() -> dict:
    """Get summary statistics about the corpus."""
    statuses = [e["status"] for e in MOCK_CORPUS]
    return {
        "total": len(MOCK_CORPUS),
        "certified": statuses.count("certified"),
        "draft": statuses.count("draft"),
        "expired": statuses.count("expired"),
    }
