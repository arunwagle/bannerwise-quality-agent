# Databricks notebook source
# MAGIC %md
# MAGIC # Setup UC Access
# MAGIC Configures app SP access to Unity Catalog resources (catalog, schema, tables) and SQL warehouse.

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text('catalog_name', 'aw_serverless_stable_catalog')
dbutils.widgets.text('schema_name', 'bannerhealth')
dbutils.widgets.text('app_sp_id', '')
dbutils.widgets.text('sql_warehouse_id', '')

CATALOG = dbutils.widgets.get('catalog_name')
SCHEMA = dbutils.widgets.get('schema_name')
APP_SP_ID = dbutils.widgets.get('app_sp_id')
WAREHOUSE_ID = dbutils.widgets.get('sql_warehouse_id')

assert APP_SP_ID, "app_sp_id parameter is required"
assert WAREHOUSE_ID, "sql_warehouse_id parameter is required"

# Resolve SP ID to display name
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
sp = w.service_principals.get(id=APP_SP_ID)
APP_SP = sp.display_name

print(f"Catalog: {CATALOG}")
print(f"Schema: {SCHEMA}")
print(f"App SP: {APP_SP} (ID: {APP_SP_ID})")
print(f"Warehouse: {WAREHOUSE_ID}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Unity Catalog Access
# MAGIC Grants the app SP access to browse and read from the catalog and schema.

# COMMAND ----------

# DBTITLE 1,Grant UC catalog and schema access
# Grant USE CATALOG
spark.sql(f"GRANT USE CATALOG ON CATALOG `{CATALOG}` TO `{APP_SP}`")
print(f"✓ Granted USE CATALOG on {CATALOG} to {APP_SP}")

# Grant USE SCHEMA
spark.sql(f"GRANT USE SCHEMA ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `{APP_SP}`")
print(f"✓ Granted USE SCHEMA on {CATALOG}.{SCHEMA} to {APP_SP}")

# Grant SELECT on all tables in the schema
spark.sql(f"GRANT SELECT ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `{APP_SP}`")
print(f"✓ Granted SELECT on {CATALOG}.{SCHEMA} to {APP_SP}")

# COMMAND ----------

# DBTITLE 1,Step 2: SQL Warehouse Access
# MAGIC %md
# MAGIC ## Step 2: SQL Warehouse Access
# MAGIC Grants CAN_USE on the SQL warehouse so the app SP can execute queries.

# COMMAND ----------

# DBTITLE 1,Grant SQL warehouse CAN_USE
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Grant CAN_USE on the SQL warehouse using the SDK's api_client
payload = {
    "access_control_list": [
        {
            "service_principal_name": APP_SP,
            "all_permissions": [{"permission_level": "CAN_USE"}],
        }
    ]
}

w.api_client.do(
    "PATCH",
    f"/api/2.0/permissions/warehouses/{WAREHOUSE_ID}",
    body=payload,
)
print(f"✓ Granted CAN_USE on warehouse {WAREHOUSE_ID} to {APP_SP}")

# COMMAND ----------

# DBTITLE 1,Verify access
# Verify: list grants on the schema
result = spark.sql(f"SHOW GRANTS `{APP_SP}` ON SCHEMA `{CATALOG}`.`{SCHEMA}`")
display(result)
print("\n✅ UC access setup complete")