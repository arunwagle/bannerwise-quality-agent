# Databricks notebook source
# MAGIC %md
# MAGIC # Cleanup Registered Model
# MAGIC Removes the registered model and all its versions from Unity Catalog.

# COMMAND ----------

dbutils.widgets.text('catalog_name', 'aw_serverless_stable_catalog')
dbutils.widgets.text('schema_name', 'bannerhealth')
dbutils.widgets.text('model_name', 'bannerwise_quality_router')

CATALOG = dbutils.widgets.get('catalog_name')
SCHEMA = dbutils.widgets.get('schema_name')
MODEL_NAME = dbutils.widgets.get('model_name')

FULL_MODEL_NAME = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"
print(f"Model to remove: {FULL_MODEL_NAME}")

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

try:
    # Delete all versions and the model itself
    w.registered_models.delete(full_name=FULL_MODEL_NAME)
    print(f"\u2713 Deleted registered model: {FULL_MODEL_NAME}")
except Exception as e:
    if "NOT_FOUND" in str(e) or "RESOURCE_DOES_NOT_EXIST" in str(e):
        print(f"\u2139 Model '{FULL_MODEL_NAME}' does not exist (already cleaned up)")
    else:
        raise e

# COMMAND ----------

# Verify model is gone
try:
    w.registered_models.get(full_name=FULL_MODEL_NAME)
    print(f"\u26a0 Model '{FULL_MODEL_NAME}' still exists!")
except Exception as e:
    print(f"\u2705 Confirmed: model '{FULL_MODEL_NAME}' no longer exists")
