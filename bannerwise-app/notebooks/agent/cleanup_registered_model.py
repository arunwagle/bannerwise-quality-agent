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

# DBTITLE 1,Delete all model versions then the model
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

try:
    # Step 1: Delete all model versions first (required before model deletion)
    versions = list(w.model_versions.list(full_name=FULL_MODEL_NAME))
    print(f"Found {len(versions)} model version(s) to remove")
    
    for v in versions:
        w.model_versions.delete(full_name=FULL_MODEL_NAME, version=v.version)
        print(f"  \u2713 Deleted version {v.version} (aliases: {v.aliases})")
    
    # Step 2: Delete the model itself (now empty)
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