# Databricks notebook source
# MAGIC %md
# MAGIC # Create Data Model Tables
# MAGIC
# MAGIC Creates the Bannerwise Quality Agent tables if they do not already exist.

# COMMAND ----------

dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")

catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")

print(f"Target: {catalog_name}.{schema_name}")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog_name}.{schema_name}")
spark.sql(f"USE CATALOG {catalog_name}")
spark.sql(f"USE SCHEMA {schema_name}")
print(f"Using {catalog_name}.{schema_name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Certified QA Corpus

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.{schema_name}.certified_qa_corpus (
    id                  STRING        NOT NULL  COMMENT 'Unique corpus entry identifier (e.g. QA-0001)',
    question            STRING        NOT NULL  COMMENT 'Certified question text',
    question_embedding  ARRAY<FLOAT>            COMMENT 'Vector embedding of the question (populated by VS sync)',
    parameterized_sql   STRING        NOT NULL  COMMENT 'Pre-approved parameterized SQL template',
    answer_template     STRING        NOT NULL  COMMENT 'Jinja-style answer template with placeholders',
    parameters          ARRAY<STRING>           COMMENT 'List of parameter names expected in the SQL',
    status              STRING                  COMMENT 'Entry status: certified | draft | expired',
    certified_by        STRING                  COMMENT 'Email of the SME who certified this entry',
    certified_date      TIMESTAMP               COMMENT 'When the entry was certified',
    next_review_date    DATE          NOT NULL  COMMENT 'Staleness gate - entries past this date are demoted',
    created_at          TIMESTAMP               COMMENT 'Row creation timestamp',
    updated_at          TIMESTAMP               COMMENT 'Last modification timestamp'
)
COMMENT 'SME-certified Q&A corpus for the deterministic confidence gate. Source for Vector Search Delta Sync index.'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true'
)
""")
print("certified_qa_corpus created")

# COMMAND ----------

# DBTITLE 1,1b. Certified QA Corpus Draft (Pending Certification)
# MAGIC %md
# MAGIC ## 1b. Certified QA Corpus Draft
# MAGIC Staging table for entries pending SME certification. Once certified, entries move to `certified_qa_corpus` and auto-sync to Vector Search.

# COMMAND ----------

# DBTITLE 1,Create draft table
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.{schema_name}.certified_qa_corpus_draft (
    id                  STRING        NOT NULL  COMMENT 'Draft entry identifier (e.g. DRAFT-A1B2C3D4)',
    question            STRING        NOT NULL  COMMENT 'Proposed certified question text',
    parameterized_sql   STRING        NOT NULL  COMMENT 'Proposed parameterized SQL template',
    answer_template     STRING        NOT NULL  COMMENT 'Proposed answer template',
    parameters          STRING                  COMMENT 'JSON array of parameter names',
    submitted_by        STRING                  COMMENT 'Who submitted this draft for certification',
    original_prompt     STRING                  COMMENT 'The original user prompt that triggered this draft',
    created_at          TIMESTAMP               COMMENT 'When the draft was submitted'
)
COMMENT 'Staging table for Q&A entries pending SME certification. Certified entries are promoted to certified_qa_corpus.'
""")
print("certified_qa_corpus_draft created")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Query History

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.{schema_name}.query_history (
    id              STRING        NOT NULL  COMMENT 'Unique query history entry identifier',
    user_email      STRING        NOT NULL  COMMENT 'Workspace identity of the user who asked',
    prompt          STRING        NOT NULL  COMMENT 'Original user prompt text',
    lane            STRING        NOT NULL  COMMENT 'Routing decision: certified | analytical',
    confidence      FLOAT                   COMMENT 'Calibrated confidence score (0.0 - 1.0)',
    badge           STRING                  COMMENT 'Display badge: HUMAN APPROVED | NOT YET APPROVED',
    corpus_id       STRING                  COMMENT 'Matched corpus entry ID (NULL for analytical lane)',
    sql_executed    STRING                  COMMENT 'SQL that was executed (certified SQL or Genie SQL)',
    answer          STRING                  COMMENT 'Final answer returned to the user',
    latency_ms      INT                     COMMENT 'End-to-end latency in milliseconds',
    timestamp       TIMESTAMP               COMMENT 'When the query was processed'
)
COMMENT 'Audit log of all user queries routed through the confidence gate.'
TBLPROPERTIES (
    'delta.enableChangeDataFeed' = 'true'
)
""")
print("query_history created")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. SME Review Queue

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.{schema_name}.sme_review_queue (
    id              STRING        NOT NULL  COMMENT 'Unique review request identifier',
    prompt          STRING        NOT NULL  COMMENT 'Original user question',
    genie_sql       STRING                  COMMENT 'SQL generated by the Genie Conversation API',
    genie_answer    STRING                  COMMENT 'Answer generated by Genie',
    requested_by    STRING        NOT NULL  COMMENT 'User who requested the review',
    requested_at    TIMESTAMP               COMMENT 'When the review was requested',
    status          STRING                  COMMENT 'Review status: pending | approved | rejected',
    reviewed_by     STRING                  COMMENT 'SME who reviewed (NULL if pending)',
    reviewed_at     TIMESTAMP               COMMENT 'When the review was completed',
    notes           STRING                  COMMENT 'SME review notes'
)
COMMENT 'Certification flywheel queue - analytical lane responses submitted for SME review.'
""")
print("sme_review_queue created")

# COMMAND ----------

# DBTITLE 1,Summary
print(f"\nAll tables created in {catalog_name}.{schema_name}")
for table in ["certified_qa_corpus", "certified_qa_corpus_draft", "query_history", "sme_review_queue"]:
    print(f"  {catalog_name}.{schema_name}.{table}")