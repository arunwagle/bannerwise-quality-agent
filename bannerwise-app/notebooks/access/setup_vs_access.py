# Databricks notebook source
# MAGIC %md
# MAGIC # Setup VS Endpoint Access
# MAGIC Configures app SP query access to the Vector Search endpoint.

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text('app_sp_id', '')
dbutils.widgets.text('vs_endpoint_name', 'bannerwise-vs-endpoint')

APP_SP_ID = dbutils.widgets.get('app_sp_id')
VS_ENDPOINT = dbutils.widgets.get('vs_endpoint_name')

assert APP_SP_ID, "app_sp_id parameter is required"
assert VS_ENDPOINT, "vs_endpoint_name parameter is required"

# Resolve SP ID to display name
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
sp = w.service_principals.get(id=APP_SP_ID)
APP_SP = sp.display_name

print(f"App SP ID: {APP_SP_ID}")
print(f"App SP Name: {APP_SP}")
print(f"VS Endpoint: {VS_ENDPOINT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant Vector Search Endpoint Access
# MAGIC Grants CAN_USE on the VS endpoint so the app SP can query the index.

# COMMAND ----------

# DBTITLE 1,Grant VS endpoint access to app SP
# Grant CAN_USE on the VS endpoint
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
    f"/api/2.0/permissions/vector-search-endpoints/{VS_ENDPOINT}",
    body=payload,
)
print(f"✓ Granted CAN_USE on VS endpoint '{VS_ENDPOINT}' to {APP_SP}")

# COMMAND ----------

# DBTITLE 1,Verify VS endpoint access
# Verify the permissions were applied
resp = w.api_client.do(
    "GET",
    f"/api/2.0/permissions/vector-search-endpoints/{VS_ENDPOINT}",
)
acl = resp.get("access_control_list", [])
for entry in acl:
    if entry.get("service_principal_name") == APP_SP:
        perms = [p["permission_level"] for p in entry.get("all_permissions", [])]
        print(f"✅ Verified: {APP_SP} has {perms} on {VS_ENDPOINT}")
        break
else:
    print(f"⚠️ Could not verify permissions for {APP_SP}")