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
# MAGIC ## Wait for Endpoint to be Ready

# COMMAND ----------

print(f"Waiting for endpoint '{ENDPOINT_NAME}' to be ready...")
max_wait_min = 15
start = time.time()

while True:
    endpoint = w.serving_endpoints.get(ENDPOINT_NAME)
    state = endpoint.state

    if state.ready == "READY":
        elapsed = (time.time() - start) / 60
        print(f"\n✓ Endpoint READY in {elapsed:.1f} minutes")
        print(f"  URL: https://{w.config.host}/serving-endpoints/{ENDPOINT_NAME}/invocations")
        break
    elif state.config_update == "UPDATE_FAILED":
        raise Exception(f"Endpoint update FAILED: {state}")

    elapsed = (time.time() - start) / 60
    if elapsed > max_wait_min:
        print(f"\n⚠ Endpoint not ready after {max_wait_min} min (state: {state})")
        print("  The endpoint may still be starting up. Check the UI.")
        break

    print(f"  State: {state.ready} / config: {state.config_update} ({elapsed:.1f} min)")
    time.sleep(30)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Validate Endpoint

# COMMAND ----------

import requests

# Quick smoke test
token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
host = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()

url = f"{host}/serving-endpoints/{ENDPOINT_NAME}/invocations"
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
payload = {
    "dataframe_records": [{"prompt": "What is the total ad spend for Q1 2025?"}]
}

response = requests.post(url, headers=headers, json=payload, timeout=60)
if response.status_code == 200:
    result = response.json()
    print(f"✓ Endpoint smoke test passed!")
    print(f"  Response: {json.dumps(result, indent=2)[:500]}")
else:
    print(f"⚠ Endpoint returned {response.status_code}: {response.text[:300]}")
    print("  This may be expected if the endpoint is still warming up.")

# COMMAND ----------

dbutils.notebook.exit(json.dumps({
    "endpoint_name": ENDPOINT_NAME,
    "model_name": FULL_MODEL_NAME,
    "model_version": str(latest_version),
    "endpoint_url": f"https://{w.config.host}/serving-endpoints/{ENDPOINT_NAME}/invocations",
}))
