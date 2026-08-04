# Databricks notebook source
# DBTITLE 1,Build Genie Space Configuration
# MAGIC %md
# MAGIC # Build Genie Space Configuration
# MAGIC
# MAGIC Generates the `serialized_space` JSON for the Bannerwise Quality Analytics Genie Space.
# MAGIC This config includes:
# MAGIC - Table data sources (11 analytics tables)
# MAGIC - General instructions for the AI
# MAGIC - Sample questions for the chat UI
# MAGIC - Example question/SQL pairs for teaching
# MAGIC - Benchmark questions for evaluation

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")
dbutils.widgets.text("sql_warehouse_id", "2d8e531640ffa469")

CATALOG = dbutils.widgets.get("catalog_name")
SCHEMA = dbutils.widgets.get("schema_name")
WAREHOUSE_ID = dbutils.widgets.get("sql_warehouse_id")

FQN = f"{CATALOG}.{SCHEMA}"
print(f"Schema: {FQN}")
print(f"Warehouse: {WAREHOUSE_ID}")

# COMMAND ----------

# DBTITLE 1,Space metadata
SPACE_TITLE = "Bannerwise Quality Analytics"

SPACE_DESCRIPTION = (
    "AI-powered analytics space for Banner Health advertising data. "
    "Ask questions about ad spend, campaign performance, banner CTR, "
    "regional metrics, channel attribution, and creative engagement."
)

print(f"Title: {SPACE_TITLE}")
print(f"Description: {SPACE_DESCRIPTION}")

# COMMAND ----------

# DBTITLE 1,General instructions
GENERAL_INSTRUCTIONS = f"""
This Genie space provides natural-language access to Bannerwise advertising analytics.
It covers 11 tables in {FQN} spanning ad spend, campaign performance, banner engagement,
regional metrics, channel attribution, and creative performance.

TABLES:
  - {FQN}.ad_metrics: Ad spend by period and campaign. Columns: period, spend, campaign_name
  - {FQN}.campaign_metrics: Campaign performance. Columns: campaign_name, campaign_type, campaign_id, impressions, clicks, conversions, revenue, spend, period
  - {FQN}.banner_performance: Banner creative performance. Columns: banner_size, ctr, engagement_rate, creative_id, creative_name, clicks, period
  - {FQN}.regional_metrics: CPM by region. Columns: region, cpm
  - {FQN}.channel_metrics: Cost per acquisition by channel. Columns: channel, spend, acquisitions
  - {FQN}.network_metrics: Ad network comparison. Columns: ad_network, impressions, ctr
  - {FQN}.session_metrics: Session duration by source. Columns: traffic_source, session_duration_sec
  - {FQN}.attribution_metrics: Revenue attribution by channel. Columns: channel, attributed_revenue, period
  - {FQN}.creative_performance: Creative-level clicks. Columns: creative_id, creative_name, clicks, period, banner_size

KEY BUSINESS CONCEPTS:
  - CTR (Click-Through Rate): clicks / impressions
  - CPA (Cost Per Acquisition): spend / acquisitions
  - CPM (Cost Per Mille): cost per 1000 impressions
  - ROI: (revenue - spend) / spend
  - Conversion Rate: conversions / clicks

QUERY RULES:
  1. Always use fully qualified table names: {FQN}.<table>
  2. Use standard SQL aggregations (SUM, AVG, COUNT)
  3. For time-based analysis, filter/group by the 'period' column
  4. For campaign analysis, join on campaign_name or campaign_id
  5. When computing rates, handle division by zero with NULLIF
"""

print(f"Instructions: {len(GENERAL_INSTRUCTIONS):,} chars")

# COMMAND ----------

# DBTITLE 1,Sample questions
SAMPLE_QUESTIONS = [
    # --- Ad Spend ---
    "What is the total ad spend for Q1 2025?",
    "Which campaign has the highest spend?",
    # --- Campaign Performance ---
    "How many impressions did the holiday campaign generate?",
    "What is the conversion rate for banner campaigns?",
    "Show me the top 5 campaigns by revenue",
    # --- Banner Performance ---
    "What is the click-through rate by banner size?",
    "Which banner sizes have the best engagement rate?",
    "Show me the top performing banner creatives this quarter",
    # --- Regional ---
    "Which regions have the highest CPM?",
    "Compare CPM across all regions",
    # --- Channel & Attribution ---
    "What is the cost per acquisition by channel?",
    "What is the total revenue attributed to banner ads in Q1 2025?",
    "Which channel drives the most attributed revenue?",
    # --- Network & Sessions ---
    "How does performance compare across ad networks?",
    "What is the average session duration from banner traffic?",
]

print(f"Sample questions: {len(SAMPLE_QUESTIONS)}")

# COMMAND ----------

# DBTITLE 1,Example question SQLs
EXAMPLE_QUESTION_SQLS = [
    (
        "What is the total ad spend for Q1 2025?",
        f"SELECT SUM(spend) AS total_spend FROM {FQN}.ad_metrics WHERE period = 'Q1 2025'"
    ),
    (
        "How many impressions did the holiday campaign generate?",
        f"SELECT SUM(impressions) AS total_impressions FROM {FQN}.campaign_metrics WHERE campaign_name = 'holiday'"
    ),
    (
        "What is the click-through rate by banner size?",
        f"SELECT banner_size, AVG(ctr) AS avg_ctr FROM {FQN}.banner_performance GROUP BY banner_size ORDER BY avg_ctr DESC"
    ),
    (
        "What is the conversion rate for banner campaigns?",
        f"SELECT campaign_id, SUM(conversions) / NULLIF(SUM(clicks), 0) AS conversion_rate FROM {FQN}.campaign_metrics WHERE campaign_type = 'banner' GROUP BY campaign_id"
    ),
    (
        "Which regions have the highest CPM?",
        f"SELECT region, cpm FROM {FQN}.regional_metrics ORDER BY cpm DESC LIMIT 10"
    ),
    (
        "What was the ROI for the summer campaign?",
        f"SELECT (SUM(revenue) - SUM(spend)) / NULLIF(SUM(spend), 0) AS roi FROM {FQN}.campaign_metrics WHERE campaign_name = 'summer'"
    ),
    (
        "How does performance compare across ad networks?",
        f"SELECT ad_network, impressions, ctr FROM {FQN}.network_metrics ORDER BY ctr DESC"
    ),
    (
        "What is the cost per acquisition by channel?",
        f"SELECT channel, spend / NULLIF(acquisitions, 0) AS cpa FROM {FQN}.channel_metrics ORDER BY cpa ASC"
    ),
    (
        "Show me the top performing banner creatives this quarter",
        f"SELECT creative_name, banner_size, clicks FROM {FQN}.banner_performance WHERE period = 'Q1 2025' ORDER BY clicks DESC LIMIT 10"
    ),
    (
        "What is the average session duration from banner traffic?",
        f"SELECT traffic_source, AVG(session_duration_sec) AS avg_duration FROM {FQN}.session_metrics GROUP BY traffic_source ORDER BY avg_duration DESC"
    ),
    (
        "What is the total revenue attributed to banner ads in Q1 2025?",
        f"SELECT SUM(attributed_revenue) AS total_revenue FROM {FQN}.attribution_metrics WHERE period = 'Q1 2025'"
    ),
    (
        "Which channel drives the most attributed revenue?",
        f"SELECT channel, SUM(attributed_revenue) AS total_rev FROM {FQN}.attribution_metrics GROUP BY channel ORDER BY total_rev DESC"
    ),
    (
        "Which banner sizes have the best engagement rate?",
        f"SELECT banner_size, AVG(engagement_rate) AS avg_engagement FROM {FQN}.banner_performance GROUP BY banner_size ORDER BY avg_engagement DESC"
    ),
    (
        "Show me the top 5 campaigns by revenue",
        f"SELECT campaign_name, SUM(revenue) AS total_revenue FROM {FQN}.campaign_metrics GROUP BY campaign_name ORDER BY total_revenue DESC LIMIT 5"
    ),
    (
        "How many unique users clicked on holiday banners?",
        f"SELECT COUNT(DISTINCT creative_id) AS unique_creatives, SUM(clicks) AS total_clicks FROM {FQN}.creative_performance WHERE period = 'Q1 2025'"
    ),
]

print(f"Example SQLs: {len(EXAMPLE_QUESTION_SQLS)}")

# COMMAND ----------

# DBTITLE 1,Benchmark questions
BENCHMARK_QUESTIONS = [
    (
        "Total advertising expenditure in Q1 2025",
        f"SELECT SUM(spend) AS total_spend FROM {FQN}.ad_metrics WHERE period = 'Q1 2025'"
    ),
    (
        "Number of impressions for the holiday campaign",
        f"SELECT SUM(impressions) AS total_impressions FROM {FQN}.campaign_metrics WHERE campaign_name = 'holiday'"
    ),
    (
        "Average CTR broken down by banner dimensions",
        f"SELECT banner_size, AVG(ctr) AS avg_ctr FROM {FQN}.banner_performance GROUP BY banner_size ORDER BY avg_ctr DESC"
    ),
    (
        "Banner campaign conversion percentage",
        f"SELECT campaign_id, SUM(conversions) / NULLIF(SUM(clicks), 0) AS conversion_rate FROM {FQN}.campaign_metrics WHERE campaign_type = 'banner' GROUP BY campaign_id"
    ),
    (
        "Top regions ranked by cost per thousand impressions",
        f"SELECT region, cpm FROM {FQN}.regional_metrics ORDER BY cpm DESC"
    ),
    (
        "Return on investment for the summer advertising campaign",
        f"SELECT (SUM(revenue) - SUM(spend)) / NULLIF(SUM(spend), 0) AS roi FROM {FQN}.campaign_metrics WHERE campaign_name = 'summer'"
    ),
    (
        "Compare click-through rates by advertising network",
        f"SELECT ad_network, impressions, ctr FROM {FQN}.network_metrics ORDER BY ctr DESC"
    ),
    (
        "Customer acquisition cost per marketing channel",
        f"SELECT channel, spend / NULLIF(acquisitions, 0) AS cpa FROM {FQN}.channel_metrics ORDER BY cpa ASC"
    ),
    (
        "Best performing creatives by click volume this period",
        f"SELECT creative_name, banner_size, clicks FROM {FQN}.banner_performance WHERE period = 'Q1 2025' ORDER BY clicks DESC LIMIT 10"
    ),
    (
        "Average time spent on site from banner ad traffic",
        f"SELECT traffic_source, AVG(session_duration_sec) AS avg_duration FROM {FQN}.session_metrics GROUP BY traffic_source ORDER BY avg_duration DESC"
    ),
    (
        "Total attributed revenue from banner advertising Q1 2025",
        f"SELECT SUM(attributed_revenue) AS total_revenue FROM {FQN}.attribution_metrics WHERE period = 'Q1 2025'"
    ),
    (
        "Which marketing channel generates the highest revenue",
        f"SELECT channel, SUM(attributed_revenue) AS total_rev FROM {FQN}.attribution_metrics GROUP BY channel ORDER BY total_rev DESC"
    ),
]

print(f"Benchmark questions: {len(BENCHMARK_QUESTIONS)}")

# COMMAND ----------

# DBTITLE 1,Build serialized_space JSON
import json
import uuid

def _sorted_hex_ids(n: int) -> list:
    """Generate n sorted 32-char lowercase hex UUIDs."""
    return sorted(uuid.uuid4().hex for _ in range(n))


def build_serialized_space(
    general_instructions, table_names, sample_questions, example_question_sqls, benchmark_questions
) -> str:
    """Build serialized_space JSON for Genie Space API."""
    sq_ids = _sorted_hex_ids(len(sample_questions))
    eq_ids = _sorted_hex_ids(len(example_question_sqls))
    bm_ids = _sorted_hex_ids(len(benchmark_questions))
    ti_id = uuid.uuid4().hex

    # Sample questions
    config_sq = [{"id": sq_ids[i], "question": [q]} for i, q in enumerate(sample_questions)]

    # Table data sources
    table_list = [{"identifier": t, "description": [f"Analytics table: {t.split('.')[-1]}"]} for t in table_names]

    # Instructions
    text_instr = [{"id": ti_id, "content": [general_instructions]}]
    ex_sqls = [{"id": eq_ids[i], "question": [q], "sql": [sql]} for i, (q, sql) in enumerate(example_question_sqls)]

    # Benchmarks
    bm_list = [
        {"id": bm_ids[i], "question": [q], "answer": [{"format": "SQL", "content": [sql]}]}
        for i, (q, sql) in enumerate(benchmark_questions)
    ]

    payload = {
        "version": 2,
        "config": {"sample_questions": config_sq},
        "data_sources": {"tables": table_list},
        "instructions": {
            "text_instructions": text_instr,
            "example_question_sqls": ex_sqls,
        },
        "benchmarks": {"questions": bm_list},
    }
    return json.dumps(payload)


# Get all analytics tables in the schema
TABLE_NAMES = [
    f"{FQN}.ad_metrics",
    f"{FQN}.attribution_metrics",
    f"{FQN}.banner_performance",
    f"{FQN}.campaign_metrics",
    f"{FQN}.channel_metrics",
    f"{FQN}.creative_performance",
    f"{FQN}.network_metrics",
    f"{FQN}.regional_metrics",
    f"{FQN}.session_metrics",
]

serialized_space = build_serialized_space(
    general_instructions=GENERAL_INSTRUCTIONS,
    table_names=TABLE_NAMES,
    sample_questions=SAMPLE_QUESTIONS,
    example_question_sqls=EXAMPLE_QUESTION_SQLS,
    benchmark_questions=BENCHMARK_QUESTIONS,
)

print(f"\u2713 Serialized space JSON: {len(serialized_space):,} chars")
print(f"  Tables: {len(TABLE_NAMES)}")
print(f"  Sample Qs: {len(SAMPLE_QUESTIONS)}")
print(f"  Example SQLs: {len(EXAMPLE_QUESTION_SQLS)}")
print(f"  Benchmarks: {len(BENCHMARK_QUESTIONS)}")

# COMMAND ----------

# DBTITLE 1,Output config for next task
# Pass config to next task via notebook exit
output = json.dumps({
    "space_title": SPACE_TITLE,
    "space_description": SPACE_DESCRIPTION,
    "warehouse_id": WAREHOUSE_ID,
    "serialized_space": serialized_space,
})

dbutils.notebook.exit(output)

# COMMAND ----------

