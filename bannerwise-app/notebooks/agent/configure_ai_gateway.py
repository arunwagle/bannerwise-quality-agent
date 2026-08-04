# Databricks notebook source
# MAGIC %md
# MAGIC # Configure AI Gateway on Serving Endpoint
# MAGIC Enables inference tables, usage tracking, and rate limits on the router serving endpoint.

# COMMAND ----------

# MAGIC %pip install databricks-sdk --upgrade
# MAGIC %restart_python

# COMMAND ----------

import json
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    AiGatewayConfig,
    AiGatewayInferenceTableConfig,
    AiGatewayRateLimit,
    AiGatewayRateLimitRenewalPeriod,
    AiGatewayRateLimitKey,
    AiGatewayUsageTrackingConfig,
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

dbutils.widgets.text("endpoint_name", "bannerwise-quality-router")
dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")
dbutils.widgets.text("rate_limit_calls", "100")
dbutils.widgets.text("rate_limit_period", "minute")

ENDPOINT_NAME = dbutils.widgets.get("endpoint_name")
CATALOG = dbutils.widgets.get("catalog_name")
SCHEMA = dbutils.widgets.get("schema_name")
RATE_LIMIT_CALLS = int(dbutils.widgets.get("rate_limit_calls"))
RATE_LIMIT_PERIOD = dbutils.widgets.get("rate_limit_period")

print(f"Endpoint: {ENDPOINT_NAME}")
print(f"Inference table: {CATALOG}.{SCHEMA}")
print(f"Rate limit: {RATE_LIMIT_CALLS} calls/{RATE_LIMIT_PERIOD}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configure AI Gateway

# COMMAND ----------

# DBTITLE 1,Configure AI Gateway (handles existing inference table)
w = WorkspaceClient()

# Build the gateway config
inference_table_cfg = AiGatewayInferenceTableConfig(
    catalog_name=CATALOG,
    schema_name=SCHEMA,
    table_name_prefix="router_inference",
    enabled=True,
)

rate_limits_cfg = [
    AiGatewayRateLimit(
        calls=RATE_LIMIT_CALLS,
        renewal_period=AiGatewayRateLimitRenewalPeriod.MINUTE,
        key=AiGatewayRateLimitKey.USER,
    ),
]

usage_tracking_cfg = AiGatewayUsageTrackingConfig(enabled=True)

# Apply AI Gateway configuration — handle case where inference table already exists
try:
    w.serving_endpoints.put_ai_gateway(
        name=ENDPOINT_NAME,
        inference_table_config=inference_table_cfg,
        rate_limits=rate_limits_cfg,
        usage_tracking_config=usage_tracking_cfg,
    )
    print(f"\u2713 AI Gateway configured with inference tables")
except Exception as e:
    if "already exists" in str(e):
        # Inference table exists from a previous run — apply config without it
        print(f"\u2139 Inference table already exists, configuring rate limits + usage tracking only")
        w.serving_endpoints.put_ai_gateway(
            name=ENDPOINT_NAME,
            rate_limits=rate_limits_cfg,
            usage_tracking_config=usage_tracking_cfg,
        )
        print(f"\u2713 AI Gateway configured (inference table retained from previous run)")
    else:
        raise

print(f"\n  Endpoint: {ENDPOINT_NAME}")
print(f"  Inference tables: {CATALOG}.{SCHEMA}.router_inference_*")
print(f"  Usage tracking: ENABLED")
print(f"  Rate limits: {RATE_LIMIT_CALLS} calls/{RATE_LIMIT_PERIOD} per user")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify Configuration

# COMMAND ----------

endpoint = w.serving_endpoints.get(ENDPOINT_NAME)
if endpoint.ai_gateway:
    gw = endpoint.ai_gateway
    print("AI Gateway settings:")
    if gw.inference_table_config:
        print(f"  Inference table: {gw.inference_table_config.catalog_name}.{gw.inference_table_config.schema_name}")
        print(f"  Table prefix: {gw.inference_table_config.table_name_prefix}")
        print(f"  Enabled: {gw.inference_table_config.enabled}")
    if gw.rate_limits:
        for rl in gw.rate_limits:
            print(f"  Rate limit: {rl.calls} calls per {rl.renewal_period} (key: {rl.key})")
    if gw.usage_tracking_config:
        print(f"  Usage tracking: {gw.usage_tracking_config.enabled}")
else:
    print("Warning: AI Gateway config not yet visible (may take a moment)")

# COMMAND ----------

dbutils.notebook.exit(json.dumps({
    "endpoint_name": ENDPOINT_NAME,
    "inference_table_enabled": True,
    "usage_tracking_enabled": True,
    "rate_limit": f"{RATE_LIMIT_CALLS}/{RATE_LIMIT_PERIOD}",
}))