# Databricks notebook source
# MAGIC %md
# MAGIC # Promote Challenger to Champion
# MAGIC After the eval job passes quality gates, promote the challenger model to champion.
# MAGIC Only the champion model gets deployed to the serving endpoint.

# COMMAND ----------

# MAGIC %pip install mlflow
# MAGIC %restart_python

# COMMAND ----------

import mlflow
import json

# COMMAND ----------

dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")
dbutils.widgets.text("model_name", "bannerwise_quality_router")

CATALOG = dbutils.widgets.get("catalog_name")
SCHEMA = dbutils.widgets.get("schema_name")
MODEL_NAME = dbutils.widgets.get("model_name")
FULL_MODEL_NAME = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"

print(f"Model: {FULL_MODEL_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Promote Challenger → Champion

# COMMAND ----------

mlflow.set_registry_uri("databricks-uc")
client = mlflow.MlflowClient()

# Get current challenger
try:
    challenger = client.get_model_version_by_alias(FULL_MODEL_NAME, "challenger")
    challenger_version = challenger.version
    print(f"Challenger version: {challenger_version}")
except Exception as e:
    raise Exception(f"No challenger found for {FULL_MODEL_NAME}. Run register_router_model first. Error: {e}")

# Get current champion (if exists)
old_champion_version = None
try:
    champion = client.get_model_version_by_alias(FULL_MODEL_NAME, "champion")
    old_champion_version = champion.version
    print(f"Current champion: version {old_champion_version}")

    if old_champion_version == challenger_version:
        print(f"\n Challenger is already champion (version {challenger_version}). Nothing to do.")
        dbutils.notebook.exit(json.dumps({
            "status": "ALREADY_CHAMPION",
            "model_name": FULL_MODEL_NAME,
            "version": str(challenger_version),
        }))
except Exception:
    print("No existing champion - first promotion.")

# Archive old champion if exists
if old_champion_version:
    client.set_registered_model_alias(FULL_MODEL_NAME, "archived_champion", old_champion_version)
    print(f"  Archived old champion v{old_champion_version} -> alias archived_champion")

# Promote challenger to champion
client.set_registered_model_alias(FULL_MODEL_NAME, "champion", challenger_version)
print(f"\n PROMOTED: challenger v{challenger_version} -> champion")

# COMMAND ----------

dbutils.jobs.taskValues.set(key="champion_version", value=str(challenger_version))
dbutils.jobs.taskValues.set(key="model_name", value=FULL_MODEL_NAME)
dbutils.notebook.exit(json.dumps({
    "status": "PROMOTED",
    "model_name": FULL_MODEL_NAME,
    "new_champion_version": str(challenger_version),
    "previous_champion_version": str(old_champion_version) if old_champion_version else None,
}))
