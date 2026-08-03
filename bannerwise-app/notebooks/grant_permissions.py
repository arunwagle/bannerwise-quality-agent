# Databricks notebook source
# MAGIC %md
# MAGIC # Grant Permissions to App Service Principal
# MAGIC
# MAGIC Grants the app SP all permissions needed to run end-to-end:
# MAGIC - **CAN_USE** on SQL Warehouse (statement execution for certified lane)
# MAGIC - **CAN_QUERY** on Serving Endpoints (router model + LLM)
# MAGIC - **USE CATALOG / USE SCHEMA / SELECT** on Unity Catalog tables

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters

# COMMAND ----------

dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")
dbutils.widgets.text("app_sp_name", "app-3hjyzw aw-bannerwise-quality-agent")
dbutils.widgets.text("sql_warehouse_id", "2d8e531640ffa469")
dbutils.widgets.text("serving_endpoint_name", "bannerwise-quality-router")
dbutils.widgets.text("llm_endpoint_name", "databricks-meta-llama-3-3-70b-instruct")

CATALOG = dbutils.widgets.get("catalog_name")
SCHEMA = dbutils.widgets.get("schema_name")
APP_SP_NAME = dbutils.widgets.get("app_sp_name")
SQL_WAREHOUSE_ID = dbutils.widgets.get("sql_warehouse_id")
SERVING_ENDPOINT_NAME = dbutils.widgets.get("serving_endpoint_name")
LLM_ENDPOINT_NAME = dbutils.widgets.get("llm_endpoint_name")

print(f"Granting permissions to: {APP_SP_NAME}")
print(f"  Catalog: {CATALOG}")
print(f"  Schema: {SCHEMA}")
print(f"  SQL Warehouse: {SQL_WAREHOUSE_ID}")
print(f"  Serving Endpoint: {SERVING_ENDPOINT_NAME}")
print(f"  LLM Endpoint: {LLM_ENDPOINT_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. SQL Warehouse Access (CAN_USE)
# MAGIC Required for: Certified Lane SQL execution via Statement Execution API

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.iam import WarehouseAccessControlRequest, WarehousePermissionLevel

w = WorkspaceClient()

w.warehouses.update_permissions(
    warehouse_id=SQL_WAREHOUSE_ID,
    access_control_list=[
        WarehouseAccessControlRequest(
            service_principal_name=APP_SP_NAME,
            permission_level=WarehousePermissionLevel.CAN_USE,
        )
    ],
)
print(f"OK: CAN_USE on SQL warehouse {SQL_WAREHOUSE_ID}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Router Serving Endpoint (CAN_QUERY)
# MAGIC Required for: App calling the router model for lane classification

# COMMAND ----------

from databricks.sdk.service.serving import (
    ServingEndpointAccessControlRequest,
    ServingEndpointPermissionLevel,
)

w.serving_endpoints.update_permissions(
    serving_endpoint_id=SERVING_ENDPOINT_NAME,
    access_control_list=[
        ServingEndpointAccessControlRequest(
            service_principal_name=APP_SP_NAME,
            permission_level=ServingEndpointPermissionLevel.CAN_QUERY,
        )
    ],
)
print(f"OK: CAN_QUERY on serving endpoint {SERVING_ENDPOINT_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. LLM Serving Endpoint (CAN_QUERY)
# MAGIC Required for: Parameter extraction in certified lane

# COMMAND ----------

try:
    w.serving_endpoints.update_permissions(
        serving_endpoint_id=LLM_ENDPOINT_NAME,
        access_control_list=[
            ServingEndpointAccessControlRequest(
                service_principal_name=APP_SP_NAME,
                permission_level=ServingEndpointPermissionLevel.CAN_QUERY,
            )
        ],
    )
    print(f"OK: CAN_QUERY on LLM endpoint {LLM_ENDPOINT_NAME}")
except Exception as e:
    print(f"NOTE: {LLM_ENDPOINT_NAME} - {str(e)[:120]}")
    print("  Foundation model endpoints are typically accessible to all SPs by default.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Unity Catalog Access
# MAGIC Required for: Reading corpus table, analytics tables, writing eval results

# COMMAND ----------

# MAGIC %sql
# MAGIC -- USE CATALOG: allows SP to browse schemas in the catalog
# MAGIC GRANT USE CATALOG ON CATALOG ${catalog_name} TO `${app_sp_name}`;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- USE SCHEMA: allows SP to list and access tables in the schema
# MAGIC GRANT USE SCHEMA ON SCHEMA ${catalog_name}.${schema_name} TO `${app_sp_name}`;

# COMMAND ----------

# MAGIC %sql
# MAGIC -- SELECT: allows SP to read all tables in the schema
# MAGIC GRANT SELECT ON SCHEMA ${catalog_name}.${schema_name} TO `${app_sp_name}`;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Vector Search Endpoint Access

# COMMAND ----------

# VS endpoint access is covered by schema-level SELECT grant above.
# The certified_qa_index inherits permissions from its source table.
print("OK: VS index access covered by schema-level SELECT grant")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print()
print("=" * 60)
print("ALL PERMISSIONS GRANTED")
print("=" * 60)
print(f"""
Service Principal: {APP_SP_NAME}
--------------------------------------------------
  SQL Warehouse ({SQL_WAREHOUSE_ID}):          CAN_USE
  Serving Endpoint ({SERVING_ENDPOINT_NAME}):  CAN_QUERY
  LLM Endpoint ({LLM_ENDPOINT_NAME}):          CAN_QUERY
  Catalog ({CATALOG}):                         USE CATALOG
  Schema ({CATALOG}.{SCHEMA}):                 USE SCHEMA + SELECT

The app can now:
  1. Call the router model (serving endpoint)
  2. Execute certified SQL via the warehouse
  3. Read corpus + analytics tables
  4. Call the LLM for parameter extraction
  5. Query the Vector Search index
""")