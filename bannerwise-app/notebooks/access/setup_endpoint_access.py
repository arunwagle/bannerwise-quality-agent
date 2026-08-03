# Databricks notebook source
# MAGIC %md
# MAGIC # Setup Serving Endpoint Access
# MAGIC Configures app SP query access to model serving endpoints (router + LLM).

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text('app_sp_name', '')
dbutils.widgets.text('serving_endpoint_name', 'bannerwise-quality-router')
dbutils.widgets.text('llm_endpoint_name', 'databricks-meta-llama-3-3-70b-instruct')

APP_SP = dbutils.widgets.get('app_sp_name')
ROUTER_ENDPOINT = dbutils.widgets.get('serving_endpoint_name')
LLM_ENDPOINT = dbutils.widgets.get('llm_endpoint_name')

assert APP_SP, "app_sp_name parameter is required"
assert ROUTER_ENDPOINT, "serving_endpoint_name parameter is required"

print(f"App SP: {APP_SP}")
print(f"Router Endpoint: {ROUTER_ENDPOINT}")
print(f"LLM Endpoint: {LLM_ENDPOINT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant Serving Endpoint Access
# MAGIC Grants CAN_QUERY on the router model endpoint and the LLM foundation model endpoint.

# COMMAND ----------

# DBTITLE 1,Grant serving endpoint access to app SP
import requests
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Authenticate
token = w.config.authenticate()
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
host = w.config.host.rstrip("/")

def grant_endpoint_access(endpoint_name: str, sp_name: str):
    """Grant CAN_QUERY on a serving endpoint to the given SP."""
    payload = {
        "access_control_list": [
            {
                "service_principal_name": sp_name,
                "all_permissions": [{"permission_level": "CAN_QUERY"}],
            }
        ]
    }
    resp = requests.patch(
        f"{host}/api/2.0/permissions/serving-endpoints/{endpoint_name}",
        headers=headers,
        json=payload,
    )
    if resp.status_code == 200:
        print(f"\u2713 Granted CAN_QUERY on '{endpoint_name}' to {sp_name}")
    else:
        print(f"\u2717 Failed for '{endpoint_name}': {resp.status_code} - {resp.text}")
        resp.raise_for_status()

# Grant access to the router model endpoint
grant_endpoint_access(ROUTER_ENDPOINT, APP_SP)

# Grant access to the LLM foundation model endpoint (for parameter extraction)
if LLM_ENDPOINT:
    grant_endpoint_access(LLM_ENDPOINT, APP_SP)

# COMMAND ----------

# DBTITLE 1,Verify endpoint access
# Verify permissions on the router endpoint
def verify_endpoint_access(endpoint_name: str, sp_name: str):
    resp = requests.get(
        f"{host}/api/2.0/permissions/serving-endpoints/{endpoint_name}",
        headers=headers,
    )
    if resp.status_code == 200:
        acl = resp.json().get("access_control_list", [])
        for entry in acl:
            if entry.get("service_principal_name") == sp_name:
                perms = [p["permission_level"] for p in entry.get("all_permissions", [])]
                print(f"\u2705 Verified: {sp_name} has {perms} on '{endpoint_name}'")
                return True
        print(f"\u26a0\ufe0f {sp_name} not found in ACL for '{endpoint_name}'")
    else:
        print(f"\u26a0\ufe0f Could not read permissions for '{endpoint_name}': {resp.status_code}")
    return False

verify_endpoint_access(ROUTER_ENDPOINT, APP_SP)
if LLM_ENDPOINT:
    verify_endpoint_access(LLM_ENDPOINT, APP_SP)

print("\n\u2705 Serving endpoint access setup complete")