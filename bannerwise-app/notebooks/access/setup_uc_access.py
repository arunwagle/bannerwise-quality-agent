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
dbutils.widgets.text('genie_space_id', '')

CATALOG = dbutils.widgets.get('catalog_name')
SCHEMA = dbutils.widgets.get('schema_name')
APP_SP_ID = dbutils.widgets.get('app_sp_id')
WAREHOUSE_ID = dbutils.widgets.get('sql_warehouse_id')
GENIE_SPACE_ID = dbutils.widgets.get('genie_space_id')

assert APP_SP_ID, "app_sp_id parameter is required"
assert WAREHOUSE_ID, "sql_warehouse_id parameter is required"

# Resolve SP numeric ID to application_id (UUID) — used for GRANT and permissions API
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
sp = w.service_principals.get(id=APP_SP_ID)
APP_SP_APP_ID = sp.application_id  # UUID used in GRANT statements and permissions API

print(f"Catalog: {CATALOG}")
print(f"Schema: {SCHEMA}")
print(f"App SP application_id: {APP_SP_APP_ID} (numeric ID: {APP_SP_ID})")
print(f"Warehouse: {WAREHOUSE_ID}")
print(f"Genie Space: {GENIE_SPACE_ID or '(not set)'}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Unity Catalog Access
# MAGIC Grants the app SP access to browse and read from the catalog and schema.

# COMMAND ----------

# DBTITLE 1,Grant UC catalog and schema access
# Grant USE CATALOG
spark.sql(f"GRANT USE CATALOG ON CATALOG `{CATALOG}` TO `{APP_SP_APP_ID}`")
print(f"✓ Granted USE CATALOG on {CATALOG} to {APP_SP_APP_ID}")

# Grant USE SCHEMA
spark.sql(f"GRANT USE SCHEMA ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `{APP_SP_APP_ID}`")
print(f"✓ Granted USE SCHEMA on {CATALOG}.{SCHEMA} to {APP_SP_APP_ID}")

# Grant SELECT on all tables in the schema (read access)
spark.sql(f"GRANT SELECT ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `{APP_SP_APP_ID}`")
print(f"✓ Granted SELECT on {CATALOG}.{SCHEMA} to {APP_SP_APP_ID}")

# Grant MODIFY on schema (needed for INSERT into query_history and certified_qa_corpus_draft)
spark.sql(f"GRANT MODIFY ON SCHEMA `{CATALOG}`.`{SCHEMA}` TO `{APP_SP_APP_ID}`")
print(f"✓ Granted MODIFY on {CATALOG}.{SCHEMA} to {APP_SP_APP_ID}")

# COMMAND ----------

# DBTITLE 1,Step 2: SQL Warehouse Access
# MAGIC %md
# MAGIC ## Step 2: SQL Warehouse Access
# MAGIC Grants CAN_USE on the SQL warehouse so the app SP can execute queries.

# COMMAND ----------

# DBTITLE 1,Grant SQL warehouse CAN_USE
# Grant CAN_USE on the SQL warehouse using application_id
payload = {
    "access_control_list": [
        {
            "service_principal_name": APP_SP_APP_ID,
            "permission_level": "CAN_USE",
        }
    ]
}

w.api_client.do(
    "PATCH",
    f"/api/2.0/permissions/warehouses/{WAREHOUSE_ID}",
    body=payload,
)
print(f"✓ Granted CAN_USE on warehouse {WAREHOUSE_ID} to {APP_SP_APP_ID}")

# COMMAND ----------

# DBTITLE 1,Grant Genie Space CAN_RUN
# Grant CAN_RUN on the Genie Space (if configured)
if GENIE_SPACE_ID:
    genie_payload = {
        "access_control_list": [
            {
                "service_principal_name": APP_SP_APP_ID,
                "permission_level": "CAN_RUN",
            }
        ]
    }

    try:
        w.api_client.do(
            "PATCH",
            f"/api/2.0/permissions/genie/spaces/{GENIE_SPACE_ID}",
            body=genie_payload,
        )
        print(f"\u2713 Granted CAN_RUN on Genie Space {GENIE_SPACE_ID} to {APP_SP_APP_ID}")
    except Exception as e:
        # Try alternative permissions path
        try:
            w.api_client.do(
                "PATCH",
                f"/api/2.0/permissions/dashboards/{GENIE_SPACE_ID}",
                body=genie_payload,
            )
            print(f"\u2713 Granted CAN_RUN on Genie Space {GENIE_SPACE_ID} to {APP_SP_APP_ID} (via dashboards API)")
        except Exception as e2:
            print(f"\u26a0\ufe0f Could not grant Genie Space access: {e2}")
            print(f"   You may need to grant access manually in the Genie Space UI.")
else:
    print("\u26a0\ufe0f genie_space_id not set — skipping Genie Space permissions")

# COMMAND ----------

# DBTITLE 1,Verify access
# Verify: list grants on the schema
result = spark.sql(f"SHOW GRANTS `{APP_SP_APP_ID}` ON SCHEMA `{CATALOG}`.`{SCHEMA}`")
display(result)
print("\n✅ UC access setup complete")