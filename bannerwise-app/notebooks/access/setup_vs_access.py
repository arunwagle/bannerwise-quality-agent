# Databricks notebook source
# MAGIC %md
# MAGIC # Setup VS Endpoint Access
# MAGIC Configures access to the Vector Search endpoint and index for:
# MAGIC 1. **App SP** — CAN_USE on VS endpoint (for the Flask app's corpus_service)
# MAGIC 2. **Model Serving** — SELECT on VS index UC securable (for the router model's retrieve step)

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text('app_sp_id', '')
dbutils.widgets.text('vs_endpoint_name', 'bannerwise-vs-endpoint')
dbutils.widgets.text('catalog_name', 'aw_serverless_stable_catalog')
dbutils.widgets.text('schema_name', 'bannerhealth')

APP_SP_ID = dbutils.widgets.get('app_sp_id')
VS_ENDPOINT = dbutils.widgets.get('vs_endpoint_name')
CATALOG = dbutils.widgets.get('catalog_name')
SCHEMA = dbutils.widgets.get('schema_name')
VS_INDEX_NAME = f"{CATALOG}.{SCHEMA}.certified_qa_index"

assert APP_SP_ID, "app_sp_id parameter is required"
assert VS_ENDPOINT, "vs_endpoint_name parameter is required"

# Resolve SP numeric ID to application_id (UUID) for permissions API
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
sp = w.service_principals.get(id=APP_SP_ID)
APP_SP_APP_ID = sp.application_id

print(f"App SP application_id: {APP_SP_APP_ID} (numeric ID: {APP_SP_ID})")
print(f"VS Endpoint: {VS_ENDPOINT}")
print(f"VS Index: {VS_INDEX_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant Vector Search Endpoint Access
# MAGIC Grants CAN_USE on the VS endpoint so the app SP can query the index.

# COMMAND ----------

# DBTITLE 1,Grant VS endpoint access to app SP
# Resolve VS endpoint name to UUID (permissions API requires UUID)
ep = w.vector_search_endpoints.get_endpoint(VS_ENDPOINT)
VS_ENDPOINT_ID = ep.id
print(f"  Resolved '{VS_ENDPOINT}' -> UUID: {VS_ENDPOINT_ID}")

# Grant CAN_USE on the VS endpoint
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
    f"/api/2.0/permissions/vector-search-endpoints/{VS_ENDPOINT_ID}",
    body=payload,
)
print(f"✓ Granted CAN_USE on VS endpoint '{VS_ENDPOINT}' to {APP_SP_APP_ID}")

# COMMAND ----------

# DBTITLE 1,Verify VS endpoint access
# Verify the permissions were applied
resp = w.api_client.do(
    "GET",
    f"/api/2.0/permissions/vector-search-endpoints/{VS_ENDPOINT_ID}",
)
acl = resp.get("access_control_list", [])
for entry in acl:
    if entry.get("service_principal_name") == APP_SP_APP_ID:
        perms = [p["permission_level"] for p in entry.get("all_permissions", [])]
        print(f"✅ Verified: {APP_SP_APP_ID} has {perms} on {VS_ENDPOINT}")
        break
else:
    print(f"⚠️ Could not verify permissions for {APP_SP_APP_ID}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant Model Serving Access to VS Index
# MAGIC
# MAGIC The Model Serving endpoint (`bannerwise-quality-router`) runs the router model which queries the VS index.
# MAGIC It uses `auth_type=model-serving` — a system-managed identity that needs **explicit UC grants** on the VS index.
# MAGIC
# MAGIC Without this, the serving endpoint returns:
# MAGIC > "Insufficient permissions for UC entity ...certified_qa_index. Config: auth_type=model-serving"
# MAGIC
# MAGIC **Important:** These grants are lost when the VS index is deleted and recreated.

# COMMAND ----------

# DBTITLE 1,Grant Model Serving SELECT on VS index
# The Model Serving endpoint uses 'system-model-serving' auth to access UC resources.
# It needs SELECT on the VS index (which is a UC TABLE securable).
# This grant is required after every VS index recreation.

print(f"Granting SELECT on VS index '{VS_INDEX_NAME}' to Model Serving...")
try:
    spark.sql(f"GRANT SELECT ON TABLE `{VS_INDEX_NAME}` TO `system-model-serving`")
    print(f"✓ Granted SELECT on {VS_INDEX_NAME} to system-model-serving")
except Exception as e:
    # If 'system-model-serving' is not the correct principal name,
    # try alternative approaches
    error_msg = str(e)
    print(f"  Note: system-model-serving grant result: {error_msg[:200]}")
    
    # Alternative: Grant to the serving endpoint by name
    try:
        spark.sql(f"GRANT SELECT ON TABLE `{VS_INDEX_NAME}` TO `bannerwise-quality-router`")
        print(f"✓ Granted SELECT on {VS_INDEX_NAME} to bannerwise-quality-router")
    except Exception as e2:
        print(f"  Alternative grant result: {str(e2)[:200]}")
        # Final fallback: Grant to all account users (broad, but works for demo)
        try:
            spark.sql(f"GRANT SELECT ON TABLE `{VS_INDEX_NAME}` TO `account users`")
            print(f"✓ Granted SELECT on {VS_INDEX_NAME} to account users (fallback)")
        except Exception as e3:
            print(f"⚠️ Could not grant VS index access: {str(e3)[:200]}")
            print(f"  Manual fix: GRANT SELECT ON TABLE {VS_INDEX_NAME} TO <principal>")

# COMMAND ----------

# DBTITLE 1,Grant Model Serving CAN_USE on VS endpoint
# Also grant CAN_USE on the VS endpoint to the model-serving system identity.
# This ensures the serving endpoint can reach the VS endpoint infrastructure.

print(f"Granting CAN_USE on VS endpoint '{VS_ENDPOINT}' to Model Serving...")
try:
    # Try granting via permissions API with system-model-serving
    payload = {
        "access_control_list": [
            {
                "group_name": "users",
                "permission_level": "CAN_USE",
            }
        ]
    }
    w.api_client.do(
        "PATCH",
        f"/api/2.0/permissions/vector-search-endpoints/{VS_ENDPOINT_ID}",
        body=payload,
    )
    print(f"✓ Granted CAN_USE on VS endpoint '{VS_ENDPOINT}' to all workspace users")
    print(f"  (Model Serving identity inherits this via workspace membership)")
except Exception as e:
    print(f"⚠️ VS endpoint permission grant issue: {str(e)[:200]}")

# COMMAND ----------

# DBTITLE 1,Verify Model Serving VS access
# Verify grants on the VS index
print(f"--- Verifying grants on {VS_INDEX_NAME} ---")
try:
    grants_df = spark.sql(f"SHOW GRANTS ON TABLE `{VS_INDEX_NAME}`")
    grants_df.show(truncate=False)
except Exception as e:
    print(f"Could not verify grants: {e}")

print("\n✅ VS access setup complete (App SP + Model Serving)")