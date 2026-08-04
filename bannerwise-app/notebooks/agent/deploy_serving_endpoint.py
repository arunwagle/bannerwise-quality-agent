# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy Router Model to Serving Endpoint
# MAGIC Creates or updates a Model Serving endpoint for the registered router model.

# COMMAND ----------

# MAGIC %pip install databricks-sdk mlflow
# MAGIC %restart_python

# COMMAND ----------

import time
import json
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    EndpointCoreConfigInput,
    ServedEntityInput,
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

# DBTITLE 1,Configuration
dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")
dbutils.widgets.text("model_name", "bannerwise_quality_router")
dbutils.widgets.text("endpoint_name", "bannerwise-quality-router")
dbutils.widgets.text("workload_size", "Small")
dbutils.widgets.text("scale_to_zero", "true")

CATALOG = dbutils.widgets.get("catalog_name")
SCHEMA = dbutils.widgets.get("schema_name")
MODEL_NAME = dbutils.widgets.get("model_name")
ENDPOINT_NAME = dbutils.widgets.get("endpoint_name")
WORKLOAD_SIZE = dbutils.widgets.get("workload_size")
SCALE_TO_ZERO = dbutils.widgets.get("scale_to_zero").lower() == "true"

dbutils.widgets.text("app_sp_id", "")
APP_SP_ID = dbutils.widgets.get("app_sp_id")

FULL_MODEL_NAME = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"

print(f"Endpoint: {ENDPOINT_NAME}")
print(f"Model: {FULL_MODEL_NAME}")
print(f"Workload: {WORKLOAD_SIZE}, Scale-to-zero: {SCALE_TO_ZERO}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get Latest Model Version

# COMMAND ----------

import mlflow

mlflow.set_registry_uri("databricks-uc")
client = mlflow.MlflowClient()

# Get the champion version (only champion gets deployed to production)
try:
    champion_mv = client.get_model_version_by_alias(FULL_MODEL_NAME, "champion")
    champion_version = champion_mv.version
    print(f"✓ Champion version: {champion_version}")
except Exception as e:
    # If no champion exists, check for challenger (first deployment)
    try:
        challenger_mv = client.get_model_version_by_alias(FULL_MODEL_NAME, "challenger")
        champion_version = challenger_mv.version
        # Promote challenger to champion on first deploy
        client.set_registered_model_alias(FULL_MODEL_NAME, "champion", champion_version)
        print(f"✓ First deploy — promoted challenger v{champion_version} to champion")
    except Exception:
        raise Exception(f"No champion or challenger found for {FULL_MODEL_NAME}. Run register_router_model first.")

print(f"  Deploying champion version {champion_version} to endpoint '{ENDPOINT_NAME}'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create or Update Serving Endpoint

# COMMAND ----------

w = WorkspaceClient()

served_entities = [
    ServedEntityInput(
        entity_name=FULL_MODEL_NAME,
        entity_version=str(champion_version),
        workload_size=WORKLOAD_SIZE,
        scale_to_zero_enabled=SCALE_TO_ZERO,
    )
]

endpoint_config = EndpointCoreConfigInput(
    served_entities=served_entities,
)

# Check if endpoint exists
try:
    existing = w.serving_endpoints.get(ENDPOINT_NAME)
    print(f"Endpoint '{ENDPOINT_NAME}' exists — updating...")
    w.serving_endpoints.update_config(
        name=ENDPOINT_NAME,
        served_entities=served_entities,
    )
    print(f"✓ Endpoint updated to champion version {champion_version}")
except Exception as e:
    if "RESOURCE_DOES_NOT_EXIST" in str(e) or "does not exist" in str(e).lower():
        print(f"Endpoint '{ENDPOINT_NAME}' does not exist — creating...")
        w.serving_endpoints.create(
            name=ENDPOINT_NAME,
            config=endpoint_config,
        )
        print(f"✓ Endpoint created with champion version {champion_version}")
    else:
        raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant App Permissions

# COMMAND ----------

# DBTITLE 1,Grant App Permissions
# Grant CAN_QUERY to the app's service principal
if APP_SP_ID:
    try:
        # Resolve SP numeric ID to application_id (UUID)
        sp = w.service_principals.get(id=APP_SP_ID)
        app_sp_app_id = sp.application_id
        print(f"  Resolved SP ID {APP_SP_ID} -> application_id: {app_sp_app_id}")

        endpoint_obj = w.serving_endpoints.get(ENDPOINT_NAME)
        payload = {
            "access_control_list": [
                {
                    "service_principal_name": app_sp_app_id,
                    "permission_level": "CAN_QUERY",
                }
            ]
        }
        w.api_client.do(
            "PATCH",
            f"/api/2.0/permissions/serving-endpoints/{endpoint_obj.id}",
            body=payload,
        )
        print(f"\u2713 Granted CAN_QUERY on '{ENDPOINT_NAME}' to {app_sp_app_id}")
    except Exception as e:
        print(f"\u26a0 Permission grant failed (endpoint may not be ready): {e}")
        print("  Grant manually via UI: Serving Endpoints → Permissions")
else:
    print("\u26a0 No app_sp_id provided — skipping permission grant")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Done — Endpoint Triggered
# MAGIC The endpoint create/update has been triggered. It will warm up asynchronously.
# MAGIC No need to wait here (avoids burning DBUs while polling).

# COMMAND ----------

endpoint_url = f"https://{w.config.host}/serving-endpoints/{ENDPOINT_NAME}/invocations"
print(f"✓ Endpoint create/update triggered successfully")
print(f"  Endpoint: {ENDPOINT_NAME}")
print(f"  Model: {FULL_MODEL_NAME} v{champion_version} (champion)")
print(f"  URL: {endpoint_url}")
print(f"  Scale-to-zero: {SCALE_TO_ZERO}")
print(f"\n  Note: Endpoint will warm up asynchronously (2-10 min for first deploy)")

dbutils.notebook.exit(json.dumps({
    "endpoint_name": ENDPOINT_NAME,
    "model_name": FULL_MODEL_NAME,
    "model_version": str(champion_version),
    "endpoint_url": endpoint_url,
    "status": "TRIGGERED",
}))