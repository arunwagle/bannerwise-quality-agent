# Databricks notebook source
# MAGIC %md
# MAGIC # Generate Synthetic Data — Bannerwise Quality Agent
# MAGIC
# MAGIC Populates the data model tables with realistic synthetic data using **dbldatagen**.
# MAGIC
# MAGIC **Parameters:**
# MAGIC - `catalog_name`: Target Unity Catalog catalog
# MAGIC - `schema_name`: Target schema

# COMMAND ----------

# MAGIC %pip install dbldatagen
# MAGIC %restart_python

# COMMAND ----------

# Parameters (passed from job)
dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")

catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")

print(f"Target: {catalog_name}.{schema_name}")
spark.sql(f"USE CATALOG {catalog_name}")
spark.sql(f"USE SCHEMA {schema_name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Generate Certified QA Corpus

# COMMAND ----------

# DBTITLE 1,Generate certified QA corpus
import dbldatagen as dg
from pyspark.sql import functions as F
from pyspark.sql.types import *
from datetime import date, datetime, timedelta
import random

# Realistic question templates for banner/ad analytics
CERTIFIED_QUESTIONS = [
    "What is the total ad spend for {period}?",
    "How many impressions did the {campaign} campaign generate?",
    "What is the click-through rate by banner size?",
    "What is the conversion rate for banner campaigns?",
    "Which regions have the highest CPM?",
    "What was the ROI for the {campaign} campaign?",
    "How does performance compare across ad networks?",
    "What is the cost per acquisition by channel?",
    "Show me the top performing banner creatives this {period}",
    "What is the average session duration from banner traffic?",
    "How many unique users clicked on {campaign} banners?",
    "What is the bounce rate from banner landing pages?",
    "Which banner sizes have the best engagement rate?",
    "What is the total revenue attributed to banner ads in {period}?",
    "How does weekday vs weekend performance compare for banners?",
    "What is the frequency cap utilization across campaigns?",
    "Which geographic regions show the highest banner engagement?",
    "What is the viewability rate for our banner inventory?",
    "How has banner CTR trended over the last 6 months?",
    "What is the effective CPM by publisher?",
]

SQL_TEMPLATES = [
    "SELECT SUM(spend) AS total_spend FROM ad_metrics WHERE period = :period",
    "SELECT SUM(impressions) AS total_impressions FROM campaign_metrics WHERE campaign_name = :campaign",
    "SELECT banner_size, AVG(ctr) AS avg_ctr FROM banner_performance GROUP BY banner_size ORDER BY avg_ctr DESC",
    "SELECT campaign_id, SUM(conversions) / SUM(clicks) AS conversion_rate FROM campaign_metrics WHERE campaign_type = 'banner' GROUP BY campaign_id",
    "SELECT region, AVG(cpm) AS avg_cpm FROM regional_metrics GROUP BY region ORDER BY avg_cpm DESC LIMIT 10",
    "SELECT (SUM(revenue) - SUM(spend)) / SUM(spend) AS roi FROM campaign_metrics WHERE campaign_name = :campaign",
    "SELECT ad_network, SUM(impressions) AS impressions, AVG(ctr) AS avg_ctr FROM network_metrics GROUP BY ad_network",
    "SELECT channel, SUM(spend) / SUM(acquisitions) AS cpa FROM channel_metrics GROUP BY channel ORDER BY cpa",
    "SELECT creative_id, creative_name, SUM(clicks) AS clicks FROM creative_performance WHERE period = :period GROUP BY 1,2 ORDER BY clicks DESC LIMIT 10",
    "SELECT AVG(session_duration_sec) AS avg_duration FROM session_metrics WHERE traffic_source = 'banner'",
    "SELECT COUNT(DISTINCT user_id) AS unique_clickers FROM click_events WHERE campaign_name = :campaign",
    "SELECT AVG(bounce_rate) AS avg_bounce_rate FROM landing_page_metrics WHERE source = 'banner'",
    "SELECT banner_size, AVG(engagement_rate) AS avg_engagement FROM banner_performance GROUP BY banner_size ORDER BY avg_engagement DESC",
    "SELECT SUM(attributed_revenue) AS total_revenue FROM attribution_metrics WHERE channel = 'banner' AND period = :period",
    "SELECT CASE WHEN dayofweek(event_date) IN (1,7) THEN 'weekend' ELSE 'weekday' END AS day_type, AVG(ctr) AS avg_ctr FROM daily_metrics GROUP BY 1",
    "SELECT campaign_id, frequency_cap, AVG(actual_frequency) AS avg_frequency FROM frequency_metrics GROUP BY 1,2",
    "SELECT geo_region, SUM(engagements) AS total_engagements FROM geo_metrics WHERE ad_type = 'banner' GROUP BY geo_region ORDER BY total_engagements DESC",
    "SELECT AVG(viewability_rate) AS avg_viewability FROM inventory_metrics WHERE ad_format = 'banner'",
    "SELECT DATE_TRUNC('month', event_date) AS month, AVG(ctr) AS avg_ctr FROM daily_metrics WHERE event_date >= DATEADD(MONTH, -6, CURRENT_DATE) GROUP BY 1 ORDER BY 1",
    "SELECT publisher_name, SUM(revenue) / (SUM(impressions)/1000) AS ecpm FROM publisher_metrics GROUP BY publisher_name ORDER BY ecpm DESC",
]

ANSWER_TEMPLATES = [
    "The total ad spend for {period} was **${total_spend:,.2f}**.",
    "The {campaign} campaign generated **{total_impressions:,}** total impressions.",
    "Click-through rates by banner size:\n{results_table}",
    "The overall conversion rate for banner campaigns is **{conversion_rate:.2%}**.",
    "Top regions by CPM:\n{results_table}",
    "The ROI for the {campaign} campaign was **{roi:.1%}**.",
    "Performance comparison across ad networks:\n{results_table}",
    "Cost per acquisition by channel:\n{results_table}",
    "Top performing banner creatives for {period}:\n{results_table}",
    "The average session duration from banner traffic is **{avg_duration:.1f} seconds**.",
    "**{unique_clickers:,}** unique users clicked on {campaign} banners.",
    "The average bounce rate from banner landing pages is **{avg_bounce_rate:.1%}**.",
    "Engagement rates by banner size:\n{results_table}",
    "Total revenue attributed to banner ads in {period}: **${total_revenue:,.2f}**.",
    "Weekday vs weekend banner performance:\n{results_table}",
    "Frequency cap utilization across campaigns:\n{results_table}",
    "Geographic regions with highest banner engagement:\n{results_table}",
    "The average viewability rate for banner inventory is **{avg_viewability:.1%}**.",
    "Banner CTR trend over the last 6 months:\n{results_table}",
    "Effective CPM by publisher:\n{results_table}",
]

CERTIFIERS = [
    "jane.smith@bannerhealth.com",
    "mike.chen@bannerhealth.com",
    "sarah.jones@bannerhealth.com",
    "david.wilson@bannerhealth.com",
    "lisa.park@bannerhealth.com",
]

# Build corpus DataFrame
corpus_rows = []
for i, (q, sql, tmpl) in enumerate(zip(CERTIFIED_QUESTIONS, SQL_TEMPLATES, ANSWER_TEMPLATES)):
    params = []
    if ":period" in sql: params.append("period")
    if ":campaign" in sql: params.append("campaign")
    
    # Mix of statuses
    if i < 14:
        status = "certified"
    elif i < 17:
        status = "draft"
    else:
        status = "expired"
    
    certifier = random.choice(CERTIFIERS) if status == "certified" else None
    cert_date = datetime(2025, random.randint(1,4), random.randint(1,28)) if status == "certified" else None
    review_date = date.today() + timedelta(days=random.randint(90, 270)) if status != "expired" else date.today() - timedelta(days=random.randint(90, 365))
    
    corpus_rows.append({
        "id": f"QA-{i+1:04d}",
        "question": q,
        "question_embedding": None,
        "parameterized_sql": sql,
        "answer_template": tmpl,
        "parameters": params,
        "status": status,
        "certified_by": certifier,
        "certified_date": cert_date,
        "next_review_date": review_date,
        "created_at": datetime(2025, 1, random.randint(1,28), random.randint(8,18)),
        "updated_at": datetime(2025, random.randint(1,5), random.randint(1,28), random.randint(8,18)),
    })

corpus_schema = StructType([
    StructField("id", StringType(), False),
    StructField("question", StringType(), False),
    StructField("question_embedding", ArrayType(FloatType()), True),
    StructField("parameterized_sql", StringType(), False),
    StructField("answer_template", StringType(), False),
    StructField("parameters", ArrayType(StringType()), True),
    StructField("status", StringType(), True),
    StructField("certified_by", StringType(), True),
    StructField("certified_date", TimestampType(), True),
    StructField("next_review_date", DateType(), False),
    StructField("created_at", TimestampType(), True),
    StructField("updated_at", TimestampType(), True),
])

corpus_df = spark.createDataFrame(corpus_rows, schema=corpus_schema)
# Truncate first to avoid duplicates, then insert (preserves table properties + CDF)
spark.sql(f"TRUNCATE TABLE {catalog_name}.{schema_name}.certified_qa_corpus")
corpus_df.write.mode("append").saveAsTable(f"{catalog_name}.{schema_name}.certified_qa_corpus")
print(f"✓ Wrote {corpus_df.count()} rows to certified_qa_corpus (replaced)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Generate Query History

# COMMAND ----------

# DBTITLE 1,Generate query history
import dbldatagen as dg
from pyspark.sql import functions as F

NUM_HISTORY_ROWS = 200

# Generate synthetic query history using dbldatagen
history_spec = (
    dg.DataGenerator(spark, name="query_history", rowcount=NUM_HISTORY_ROWS, seedColumnName="row_id")
    .withColumn("id", "string", expr="concat('H-', lpad(cast(row_id as string), 6, '0'))")
    .withColumn("user_email", "string", 
                values=["arun.wagle@databricks.com", "jane.smith@bannerhealth.com",
                        "mike.chen@bannerhealth.com", "analyst1@bannerhealth.com",
                        "analyst2@bannerhealth.com"],
                random=True)
    .withColumn("prompt", "string",
                values=CERTIFIED_QUESTIONS + [
                    "Predict next quarter revenue from banners",
                    "What will our CTR be next month?",
                    "Compare Q1 vs Q2 banner performance",
                    "Show me anomalies in ad spend",
                    "Why did impressions drop last week?",
                ],
                random=True)
    .withColumn("lane", "string", values=["certified", "analytical"], weights=[60, 40], random=True)
    .withColumn("confidence", "float", minValue=0.3, maxValue=0.99, random=True)
    .withColumn("latency_ms", "int", minValue=200, maxValue=4000, random=True)
    .withColumn("timestamp", "timestamp",
                begin="2025-01-01 00:00:00", end="2025-06-30 23:59:59",
                random=True)
)

history_df = history_spec.build()

# Add derived columns based on lane
history_df = (
    history_df
    .withColumn("badge", F.when(F.col("lane") == "certified", "HUMAN APPROVED")
                          .otherwise("NOT YET APPROVED"))
    .withColumn("corpus_id", F.when(F.col("lane") == "certified",
                                     F.concat(F.lit("QA-"), F.lpad((F.floor(F.rand() * 14) + 1).cast("string"), 4, "0")))
                              .otherwise(None))
    .withColumn("sql_executed", F.lit("SELECT ... FROM ..."))  # Placeholder
    .withColumn("answer", F.lit("Synthetic answer placeholder for testing."))
    .drop("row_id")
)

spark.sql(f"TRUNCATE TABLE {catalog_name}.{schema_name}.query_history")
history_df.write.mode("append").saveAsTable(f"{catalog_name}.{schema_name}.query_history")
print(f"✓ Wrote {history_df.count()} rows to query_history (replaced)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Generate SME Review Queue

# COMMAND ----------

# DBTITLE 1,Generate SME review queue
NUM_REVIEW_ROWS = 30

review_spec = (
    dg.DataGenerator(spark, name="sme_review_queue", rowcount=NUM_REVIEW_ROWS, seedColumnName="row_id")
    .withColumn("id", "string", expr="concat('REV-', lpad(cast(row_id as string), 4, '0'))")
    .withColumn("prompt", "string",
                values=[
                    "Predict next quarter banner revenue",
                    "What will our CTR be next month?",
                    "Show me anomalies in ad spend last week",
                    "Why did impressions drop on Tuesday?",
                    "Compare performance across all publishers",
                    "What is the incrementality of banner campaigns?",
                    "Forecast holiday campaign performance",
                    "Which creatives should we retire?",
                ],
                random=True)
    .withColumn("genie_sql", "string", 
                values=[
                    "SELECT DATE_TRUNC('quarter', event_date), SUM(revenue) FROM metrics GROUP BY 1",
                    "SELECT AVG(ctr) FROM daily_metrics WHERE event_date > CURRENT_DATE",
                    "SELECT * FROM ad_spend WHERE spend > (SELECT AVG(spend)*2 FROM ad_spend)",
                ],
                random=True)
    .withColumn("genie_answer", "string", expr="concat('Generated analysis for: ', prompt)")
    .withColumn("requested_by", "string",
                values=["arun.wagle@databricks.com", "analyst1@bannerhealth.com",
                        "analyst2@bannerhealth.com"],
                random=True)
    .withColumn("requested_at", "timestamp",
                begin="2025-03-01 00:00:00", end="2025-06-30 23:59:59",
                random=True)
    .withColumn("status", "string", values=["pending", "approved", "rejected"], weights=[50, 35, 15], random=True)
    .withColumn("reviewed_by", "string",
                values=["jane.smith@bannerhealth.com", "mike.chen@bannerhealth.com", None],
                random=True)
    .withColumn("reviewed_at", "timestamp",
                begin="2025-04-01 00:00:00", end="2025-06-30 23:59:59",
                random=True)
    .withColumn("notes", "string", values=["Looks good - approved for corpus", "SQL needs refinement", "Out of scope", None], random=True)
)

review_df = review_spec.build().drop("row_id")

# NULL out reviewed fields for pending entries
review_df = (
    review_df
    .withColumn("reviewed_by", F.when(F.col("status") == "pending", None).otherwise(F.col("reviewed_by")))
    .withColumn("reviewed_at", F.when(F.col("status") == "pending", None).otherwise(F.col("reviewed_at")))
    .withColumn("notes", F.when(F.col("status") == "pending", None).otherwise(F.col("notes")))
)

spark.sql(f"TRUNCATE TABLE {catalog_name}.{schema_name}.sme_review_queue")
review_df.write.mode("append").saveAsTable(f"{catalog_name}.{schema_name}.sme_review_queue")
print(f"✓ Wrote {review_df.count()} rows to sme_review_queue (replaced)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print(f"\n{'='*60}")
print(f"  Synthetic Data Generation Complete")
print(f"  Target: {catalog_name}.{schema_name}")
print(f"{'='*60}")

for table in ["certified_qa_corpus", "query_history", "sme_review_queue"]:
    count = spark.table(f"{catalog_name}.{schema_name}.{table}").count()
    print(f"  {table}: {count} rows")

print(f"{'='*60}")