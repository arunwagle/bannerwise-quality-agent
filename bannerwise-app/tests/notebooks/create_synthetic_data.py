# Databricks notebook source
# MAGIC %md
# MAGIC # Create Synthetic Data Tables
# MAGIC
# MAGIC Generates the data tables referenced by the certified QA corpus SQL templates.
# MAGIC These tables are needed for the Certified Lane to execute SQL and return actual results.
# MAGIC
# MAGIC **Tables created:**
# MAGIC - `ad_metrics` — Ad spend by period and campaign
# MAGIC - `campaign_metrics` — Impressions, clicks, conversions, revenue
# MAGIC - `banner_performance` — CTR and engagement by banner size
# MAGIC - `regional_metrics` — CPM by region
# MAGIC - `network_metrics` — Performance by ad network
# MAGIC - `channel_metrics` — CPA by channel
# MAGIC - `session_metrics` — Session duration by traffic source
# MAGIC - `click_events` — User click events by campaign
# MAGIC - `landing_page_metrics` — Bounce rate by source
# MAGIC - `attribution_metrics` — Revenue attribution by channel
# MAGIC - `creative_performance` — Creative performance (alias view on banner_performance)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters

# COMMAND ----------

dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")

CATALOG = dbutils.widgets.get("catalog_name")
SCHEMA = dbutils.widgets.get("schema_name")

print(f"Creating synthetic data tables in: {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ad Metrics
# MAGIC Referenced by QA-0001: `SELECT SUM(spend) AS total_spend FROM ad_metrics WHERE period = :period`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.ad_metrics (
  period STRING COMMENT 'Fiscal period (e.g., Q1 2025)',
  spend DOUBLE COMMENT 'Ad spend in USD',
  campaign_name STRING COMMENT 'Campaign identifier'
)
COMMENT 'Ad spend metrics by period and campaign'
""")

spark.sql(f"""
INSERT INTO {CATALOG}.{SCHEMA}.ad_metrics VALUES
  ('Q1 2025', 125000.50, 'holiday'),
  ('Q1 2025', 87500.25, 'spring_sale'),
  ('Q1 2025', 42000.00, 'brand_awareness'),
  ('Q2 2025', 143000.75, 'summer'),
  ('Q2 2025', 95000.00, 'back_to_school'),
  ('Q3 2024', 112000.00, 'holiday'),
  ('Q4 2024', 165000.00, 'holiday'),
  ('Q4 2024', 78000.00, 'year_end_sale')
""")

print(f"✓ {CATALOG}.{SCHEMA}.ad_metrics — 8 rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Campaign Metrics
# MAGIC Referenced by QA-0002, QA-0004, QA-0006

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.campaign_metrics (
  campaign_name STRING COMMENT 'Campaign identifier',
  campaign_type STRING COMMENT 'Ad type (banner, video, native)',
  campaign_id STRING COMMENT 'Unique campaign ID',
  impressions BIGINT COMMENT 'Total impressions',
  clicks BIGINT COMMENT 'Total clicks',
  conversions BIGINT COMMENT 'Total conversions',
  revenue DOUBLE COMMENT 'Revenue attributed in USD',
  spend DOUBLE COMMENT 'Campaign spend in USD',
  period STRING COMMENT 'Fiscal period'
)
COMMENT 'Campaign-level performance metrics'
""")

spark.sql(f"""
INSERT INTO {CATALOG}.{SCHEMA}.campaign_metrics VALUES
  ('holiday', 'banner', 'C001', 2450000, 73500, 8820, 441000.00, 165000.00, 'Q4 2024'),
  ('holiday', 'banner', 'C001', 2100000, 63000, 7560, 378000.00, 125000.50, 'Q1 2025'),
  ('spring_sale', 'banner', 'C002', 1800000, 54000, 5400, 270000.00, 87500.00, 'Q1 2025'),
  ('summer', 'banner', 'C003', 3200000, 96000, 11520, 576000.00, 143000.00, 'Q2 2025'),
  ('back_to_school', 'banner', 'C004', 1500000, 45000, 4050, 202500.00, 95000.00, 'Q2 2025'),
  ('brand_awareness', 'banner', 'C005', 5000000, 50000, 2500, 125000.00, 42000.00, 'Q1 2025')
""")

print(f"✓ {CATALOG}.{SCHEMA}.campaign_metrics — 6 rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Banner Performance
# MAGIC Referenced by QA-0003, QA-0009, QA-0013

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.banner_performance (
  banner_size STRING COMMENT 'Banner dimensions (e.g., 300x250)',
  ctr DOUBLE COMMENT 'Click-through rate',
  engagement_rate DOUBLE COMMENT 'Engagement rate',
  creative_id STRING COMMENT 'Creative asset ID',
  creative_name STRING COMMENT 'Creative asset name',
  clicks BIGINT COMMENT 'Total clicks',
  period STRING COMMENT 'Fiscal period'
)
COMMENT 'Banner creative performance by size and period'
""")

spark.sql(f"""
INSERT INTO {CATALOG}.{SCHEMA}.banner_performance VALUES
  ('300x250', 0.032, 0.045, 'CR01', 'Holiday Hero', 45000, 'Q1 2025'),
  ('728x90', 0.028, 0.038, 'CR02', 'Spring Banner', 38000, 'Q1 2025'),
  ('160x600', 0.021, 0.029, 'CR03', 'Sidebar Promo', 22000, 'Q1 2025'),
  ('320x50', 0.035, 0.048, 'CR04', 'Mobile Strip', 52000, 'Q1 2025'),
  ('970x250', 0.025, 0.035, 'CR05', 'Billboard Hero', 31000, 'Q1 2025'),
  ('300x600', 0.030, 0.042, 'CR06', 'Half-Page Takeover', 41000, 'Q1 2025'),
  ('300x250', 0.029, 0.041, 'CR07', 'Summer Vibes', 39000, 'Q2 2025'),
  ('728x90', 0.031, 0.043, 'CR08', 'Back-to-School', 43000, 'Q2 2025')
""")

print(f"✓ {CATALOG}.{SCHEMA}.banner_performance — 8 rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Regional Metrics
# MAGIC Referenced by QA-0005: `SELECT region, AVG(cpm) ... FROM regional_metrics`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.regional_metrics (
  region STRING COMMENT 'Geographic region',
  cpm DOUBLE COMMENT 'Cost per mille (thousand impressions)'
)
COMMENT 'CPM performance by geographic region'
""")

spark.sql(f"""
INSERT INTO {CATALOG}.{SCHEMA}.regional_metrics VALUES
  ('Northeast', 12.50), ('Southeast', 9.75), ('Midwest', 8.20),
  ('West', 14.30), ('Southwest', 10.15), ('Northwest', 11.80),
  ('Mid-Atlantic', 13.20), ('Mountain', 7.90)
""")

print(f"✓ {CATALOG}.{SCHEMA}.regional_metrics — 8 rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Network Metrics
# MAGIC Referenced by QA-0007: `SELECT ad_network, SUM(impressions), AVG(ctr) FROM network_metrics`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.network_metrics (
  ad_network STRING COMMENT 'Ad network name',
  impressions BIGINT COMMENT 'Total impressions',
  ctr DOUBLE COMMENT 'Click-through rate'
)
COMMENT 'Performance by ad network'
""")

spark.sql(f"""
INSERT INTO {CATALOG}.{SCHEMA}.network_metrics VALUES
  ('Google Display', 8500000, 0.031),
  ('Meta Audience', 6200000, 0.028),
  ('Amazon DSP', 3100000, 0.035),
  ('Trade Desk', 2800000, 0.033),
  ('DV360', 4500000, 0.027)
""")

print(f"✓ {CATALOG}.{SCHEMA}.network_metrics — 5 rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Channel Metrics
# MAGIC Referenced by QA-0008: `SELECT channel, SUM(spend)/SUM(acquisitions) AS cpa FROM channel_metrics`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.channel_metrics (
  channel STRING COMMENT 'Acquisition channel',
  spend DOUBLE COMMENT 'Channel spend in USD',
  acquisitions INT COMMENT 'Number of customer acquisitions'
)
COMMENT 'Cost per acquisition by channel'
""")

spark.sql(f"""
INSERT INTO {CATALOG}.{SCHEMA}.channel_metrics VALUES
  ('display', 165000.00, 8820),
  ('social', 87500.00, 5400),
  ('search', 95000.00, 11520),
  ('email', 22000.00, 4050),
  ('affiliate', 45000.00, 2500),
  ('native', 38000.00, 3200)
""")

print(f"✓ {CATALOG}.{SCHEMA}.channel_metrics — 6 rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Session Metrics
# MAGIC Referenced by QA-0010: `SELECT AVG(session_duration_sec) FROM session_metrics WHERE traffic_source = 'banner'`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.session_metrics (
  traffic_source STRING COMMENT 'Traffic source (banner, organic, email, etc.)',
  session_duration_sec INT COMMENT 'Session duration in seconds'
)
COMMENT 'Session duration by traffic source'
""")

spark.sql(f"""
INSERT INTO {CATALOG}.{SCHEMA}.session_metrics VALUES
  ('banner', 185), ('banner', 220), ('banner', 145), ('banner', 310), ('banner', 175),
  ('banner', 195), ('banner', 260), ('banner', 230), ('banner', 155), ('banner', 200),
  ('organic', 420), ('organic', 380), ('organic', 350),
  ('email', 290), ('email', 260), ('email', 310),
  ('social', 95), ('social', 110), ('social', 85)
""")

print(f"✓ {CATALOG}.{SCHEMA}.session_metrics — 19 rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Click Events
# MAGIC Referenced by QA-0011: `SELECT COUNT(DISTINCT user_id) FROM click_events WHERE campaign_name = :campaign`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.click_events (
  user_id STRING COMMENT 'Unique user identifier',
  campaign_name STRING COMMENT 'Campaign that generated the click',
  click_timestamp TIMESTAMP COMMENT 'When the click occurred'
)
COMMENT 'Individual click events by user and campaign'
""")

spark.sql(f"""
INSERT INTO {CATALOG}.{SCHEMA}.click_events VALUES
  ('U001', 'holiday', '2025-01-15 10:30:00'),
  ('U002', 'holiday', '2025-01-15 11:45:00'),
  ('U003', 'holiday', '2025-01-16 09:20:00'),
  ('U001', 'holiday', '2025-01-17 14:30:00'),
  ('U004', 'holiday', '2025-01-18 16:00:00'),
  ('U005', 'spring_sale', '2025-02-01 10:00:00'),
  ('U006', 'spring_sale', '2025-02-02 11:30:00'),
  ('U007', 'spring_sale', '2025-02-03 13:45:00'),
  ('U005', 'spring_sale', '2025-02-04 09:15:00'),
  ('U008', 'summer', '2025-04-01 10:00:00'),
  ('U009', 'summer', '2025-04-02 12:00:00'),
  ('U010', 'summer', '2025-04-03 15:30:00'),
  ('U011', 'summer', '2025-04-04 11:00:00'),
  ('U012', 'summer', '2025-04-05 14:00:00'),
  ('U008', 'summer', '2025-04-06 09:00:00')
""")

print(f"✓ {CATALOG}.{SCHEMA}.click_events — 15 rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Landing Page Metrics
# MAGIC Referenced by QA-0012: `SELECT AVG(bounce_rate) FROM landing_page_metrics WHERE source = 'banner'`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.landing_page_metrics (
  source STRING COMMENT 'Traffic source',
  bounce_rate DOUBLE COMMENT 'Bounce rate (0.0-1.0)'
)
COMMENT 'Landing page bounce rates by traffic source'
""")

spark.sql(f"""
INSERT INTO {CATALOG}.{SCHEMA}.landing_page_metrics VALUES
  ('banner', 0.42), ('banner', 0.38), ('banner', 0.45), ('banner', 0.40), ('banner', 0.35),
  ('organic', 0.28), ('organic', 0.32),
  ('email', 0.22), ('email', 0.25),
  ('social', 0.55), ('social', 0.52)
""")

print(f"✓ {CATALOG}.{SCHEMA}.landing_page_metrics — 11 rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Attribution Metrics
# MAGIC Referenced by QA-0014: `SELECT SUM(attributed_revenue) FROM attribution_metrics WHERE channel = 'banner' AND period = :period`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.attribution_metrics (
  channel STRING COMMENT 'Attribution channel',
  attributed_revenue DOUBLE COMMENT 'Revenue attributed to this channel',
  period STRING COMMENT 'Fiscal period'
)
COMMENT 'Revenue attribution by channel and period'
""")

spark.sql(f"""
INSERT INTO {CATALOG}.{SCHEMA}.attribution_metrics VALUES
  ('banner', 378000.00, 'Q1 2025'),
  ('banner', 270000.00, 'Q1 2025'),
  ('banner', 125000.00, 'Q1 2025'),
  ('banner', 576000.00, 'Q2 2025'),
  ('banner', 441000.00, 'Q4 2024'),
  ('search', 520000.00, 'Q1 2025'),
  ('email', 180000.00, 'Q1 2025'),
  ('social', 95000.00, 'Q1 2025')
""")

print(f"✓ {CATALOG}.{SCHEMA}.attribution_metrics — 8 rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Creative Performance View
# MAGIC Referenced by QA-0009 (alias for banner_performance filtered view)

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {CATALOG}.{SCHEMA}.creative_performance AS
SELECT
  creative_id, creative_name, clicks, period, banner_size
FROM {CATALOG}.{SCHEMA}.banner_performance
""")

print(f"✓ {CATALOG}.{SCHEMA}.creative_performance — view on banner_performance")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

# Show all tables created
tables = spark.sql(f"SHOW TABLES IN {CATALOG}.{SCHEMA}").filter("tableName LIKE '%metric%' OR tableName LIKE '%performance%' OR tableName LIKE '%event%' OR tableName LIKE '%page%' OR tableName LIKE '%attribution%' OR tableName LIKE '%creative%'")
print(f"\n✓ All synthetic data tables created in {CATALOG}.{SCHEMA}:")
tables.show(20, truncate=False)

# Quick validation
print("\nSample queries:")
result = spark.sql(f"SELECT SUM(spend) AS total_spend FROM {CATALOG}.{SCHEMA}.ad_metrics WHERE period = 'Q1 2025'")
total = result.collect()[0]["total_spend"]
print(f"  QA-0001 'Total ad spend for Q1 2025': ${total:,.2f}")

result2 = spark.sql(f"SELECT SUM(impressions) AS total_impressions FROM {CATALOG}.{SCHEMA}.campaign_metrics WHERE campaign_name = 'holiday'")
imps = result2.collect()[0]["total_impressions"]
print(f"  QA-0002 'Impressions for holiday campaign': {imps:,}")
