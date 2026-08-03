# Databricks notebook source
# MAGIC %md
# MAGIC # Setup VS Endpoint Access
# MAGIC Configures app SP query access to the Vector Search endpoint.

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text('app_sp_name', '')
dbutils.widgets.text('vs_endpoint_name', 'bannerwise-vs-endpoint')

APP_SP = dbutils.widgets.get('app_sp_name')
VS_ENDPOINT = dbutils.widgets.get('vs_endpoint_name')

assert APP_SP, "app_sp_name parameter is required"
assert VS_ENDPOINT, "vs_endpoint_name parameter is required"

print(f"App SP: {APP_SP}")
print(f"VS Endpoint: {VS_ENDPOINT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant Vector Search Endpoint Access
# MAGIC Grants CAN_USE on the VS endpoint so the app SP can query the index.

# COMMAND ----------

# DBTITLE 1,Grant VS endpoint access to app SP
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import (
    SecurableType,
    PermissionsChange,
    Privilege,
)

w = WorkspaceClient()

# Look up the SP ID from the SP name
sp_list = list(w.service_principals.list(filter=f"displayName eq '{APP_SP}'"))
assert sp_list, f"Service principal '{APP_SP}' not found"
sp_id = sp_list[0].id
print(f"Found SP: {APP_SP} (ID: {sp_id})")

# Grant access to the Vector Search endpoint using the permissions API
import requests

token = w.config.authenticate()
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
host = w.config.host.rstrip("/")

# Get existing permissions
resp = requests.get(
    f"{host}/api/2.0/permissions/vector-search-endpoints/{VS_ENDPOINT}",
    headers=headers,
)
print(f"Current permissions status: {resp.status_code}")

# Update permissions — grant CAN_USE to the SP
payload = {
    "access_control_list": [
        {
            "service_principal_name": APP_SP,
            "all_permissions": [{"permission_level": "CAN_USE"}],
        }
    ]
}

resp = requests.patch(
    f"{host}/api/2.0/permissions/vector-search-endpoints/{VS_ENDPOINT}",
    headers=headers,
    json=payload,
)
resp.raise_for_status()
print(f"✓ Granted CAN_USE on VS endpoint '{VS_ENDPOINT}' to {APP_SP}")

# COMMAND ----------

# DBTITLE 1,Verify VS endpoint access
# Verify the permissions were applied
resp = requests.get(
    f"{host}/api/2.0/permissions/vector-search-endpoints/{VS_ENDPOINT}",
    headers=headers,
)
if resp.status_code == 200:
    acl = resp.json().get("access_control_list", [])
    for entry in acl:
        if entry.get("service_principal_name") == APP_SP:
            perms = [p["permission_level"] for p in entry.get("all_permissions", [])]
            print(f"✅ Verified: {APP_SP} has {perms} on {VS_ENDPOINT}")
            break
    else:
        print(f"⚠️ Could not verify permissions for {APP_SP}")
else:
    print(f"⚠️ Could not read permissions: {resp.status_code}")