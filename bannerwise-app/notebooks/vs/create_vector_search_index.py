# Databricks notebook source
# MAGIC %md
# MAGIC # Create Vector Search Index
# MAGIC
# MAGIC Creates the Delta Sync index on `certified_qa_corpus` for the confidence gate.
# MAGIC Must run AFTER the corpus table is populated (depends on `populate_corpus_and_history`).
# MAGIC
# MAGIC The index enables semantic similarity search against certified QA entries,
# MAGIC allowing the router agent to match user prompts to pre-approved questions.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters

# COMMAND ----------

dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")
dbutils.widgets.text("vs_endpoint_name", "bannerwise-vs-endpoint")
dbutils.widgets.text("embedding_model", "databricks-bge-large-en")

CATALOG = dbutils.widgets.get("catalog_name")
SCHEMA = dbutils.widgets.get("schema_name")
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint_name")
EMBEDDING_MODEL = dbutils.widgets.get("embedding_model")

INDEX_NAME = f"{CATALOG}.{SCHEMA}.certified_qa_index"
SOURCE_TABLE = f"{CATALOG}.{SCHEMA}.certified_qa_corpus"

print(f"Index: {INDEX_NAME}")
print(f"Source table: {SOURCE_TABLE}")
print(f"VS endpoint: {VS_ENDPOINT}")
print(f"Embedding model: {EMBEDDING_MODEL}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify source table exists

# COMMAND ----------

row_count = spark.sql(f"SELECT COUNT(*) AS cnt FROM {SOURCE_TABLE}").collect()[0]["cnt"]
print(f"Source table has {row_count} rows")
assert row_count > 0, f"Source table {SOURCE_TABLE} is empty — cannot create index"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or sync the Delta Sync index

# COMMAND ----------

# DBTITLE 1,Create or sync the Delta Sync index
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.vectorsearch import (
    DeltaSyncVectorIndexSpecRequest,
    EmbeddingSourceColumn,
    PipelineType,
    VectorIndexType,
)

w = WorkspaceClient()

COLUMNS_TO_SYNC = [
    "id", "question", "embedding_text", "parameterized_sql", "answer_template",
    "parameters", "status", "certified_by", "certified_date", "next_review_date"
]

# Check if index already exists
try:
    existing = w.vector_search_indexes.get_index(INDEX_NAME)
    print(f"Index already exists: {INDEX_NAME}")
    print(f"  Status: {existing.status.ready}")
    print(f"  Syncing index...")
    w.vector_search_indexes.sync_index(INDEX_NAME)
    print(f"  \u2713 Sync triggered.")
except Exception as e:
    if "NOT_FOUND" in str(e) or "does not exist" in str(e).lower():
        print(f"Creating new index: {INDEX_NAME}")
        w.vector_search_indexes.create_index(
            name=INDEX_NAME,
            endpoint_name=VS_ENDPOINT,
            primary_key="id",
            index_type=VectorIndexType.DELTA_SYNC,
            delta_sync_index_spec=DeltaSyncVectorIndexSpecRequest(
                source_table=SOURCE_TABLE,
                pipeline_type=PipelineType.TRIGGERED,
                embedding_source_columns=[
                    EmbeddingSourceColumn(
                        name="embedding_text",
                        embedding_model_endpoint_name=EMBEDDING_MODEL,
                    )
                ],
                columns_to_sync=COLUMNS_TO_SYNC,
            ),
        )
        print(f"\u2713 Index creation initiated (runs async — no wait).")
    else:
        raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Wait for index to be ready

# COMMAND ----------

# DBTITLE 1,Check index status (no waiting)
# Check current status without waiting (index syncs asynchronously)
import time
time.sleep(5)  # brief pause for API consistency

idx = w.vector_search_indexes.get_index(INDEX_NAME)
print(f"Index: {idx.name}")
print(f"  Ready: {idx.status.ready}")
if not idx.status.ready:
    print(f"  Index is syncing asynchronously — will be ready in a few minutes.")
    print(f"  No need to wait here. Run the router_agent_job after the index is ONLINE.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify index

# COMMAND ----------

idx = w.vector_search_indexes.get_index(INDEX_NAME)
print(f"\nIndex: {idx.name}")
print(f"  Endpoint: {VS_ENDPOINT}")
print(f"  Status ready: {idx.status.ready}")
print(f"  Source table: {SOURCE_TABLE}")
print(f"  Columns synced: {COLUMNS_TO_SYNC}")