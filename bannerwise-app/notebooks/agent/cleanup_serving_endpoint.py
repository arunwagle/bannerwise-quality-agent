# Databricks notebook source
# MAGIC %md
# MAGIC # Cleanup Serving Endpoint
# MAGIC Removes the router model serving endpoint.

# COMMAND ----------

dbutils.widgets.text('serving_endpoint_name', 'bannerwise-quality-router')

ENDPOINT = dbutils.widgets.get('serving_endpoint_name')
print(f"Endpoint to remove: {ENDPOINT}")

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

try:
    w.serving_endpoints.delete(name=ENDPOINT)
    print(f"\u2713 Deleted serving endpoint: {ENDPOINT}")
except Exception as e:
    if "NOT_FOUND" in str(e) or "RESOURCE_DOES_NOT_EXIST" in str(e):
        print(f"\u2139 Endpoint '{ENDPOINT}' does not exist (already cleaned up)")
    else:
        raise e

# COMMAND ----------

import time

# Verify endpoint is gone
time.sleep(5)
try:
    w.serving_endpoints.get(name=ENDPOINT)
    print(f"\u26a0 Endpoint '{ENDPOINT}' still exists (may be in DELETING state)")
except Exception as e:
    print(f"\u2705 Confirmed: endpoint '{ENDPOINT}' no longer exists")
