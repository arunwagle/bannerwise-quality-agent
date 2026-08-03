# Databricks notebook source
# MAGIC %md
# MAGIC # Cleanup Vector Search Index
# MAGIC Removes the Delta Sync VS index from the endpoint.

# COMMAND ----------

dbutils.widgets.text('catalog_name', 'aw_serverless_stable_catalog')
dbutils.widgets.text('schema_name', 'bannerhealth')
dbutils.widgets.text('vs_endpoint_name', 'bannerwise-vs-endpoint')

CATALOG = dbutils.widgets.get('catalog_name')
SCHEMA = dbutils.widgets.get('schema_name')
VS_ENDPOINT = dbutils.widgets.get('vs_endpoint_name')

INDEX_NAME = f"{CATALOG}.{SCHEMA}.certified_qa_index"

print(f"Index: {INDEX_NAME}")
print(f"Endpoint: {VS_ENDPOINT}")

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

try:
    w.vector_search_indexes.delete_index(index_name=INDEX_NAME)
    print(f"\u2713 Deleted VS index: {INDEX_NAME}")
except Exception as e:
    if "NOT_FOUND" in str(e) or "does not exist" in str(e):
        print(f"\u2139 Index {INDEX_NAME} does not exist (already cleaned up)")
    else:
        raise e

# COMMAND ----------

# Verify index is gone
try:
    w.vector_search_indexes.get_index(index_name=INDEX_NAME)
    print(f"\u26a0 Index {INDEX_NAME} still exists!")
except Exception as e:
    print(f"\u2705 Confirmed: index {INDEX_NAME} no longer exists")
