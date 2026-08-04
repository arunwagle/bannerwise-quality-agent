# Databricks notebook source
# MAGIC %md
# MAGIC # Setup Serving Endpoint Access
# MAGIC Configures app SP query access to model serving endpoints (router + LLM).

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text('app_sp_id', '')
dbutils.widgets.text('serving_endpoint_name', 'bannerwise-quality-router')
dbutils.widgets.text('llm_endpoint_name', 'databricks-meta-llama-3-3-70b-instruct')

APP_SP_ID = dbutils.widgets.get('app_sp_id')
ROUTER_ENDPOINT = dbutils.widgets.get('serving_endpoint_name')
LLM_ENDPOINT = dbutils.widgets.get('llm_endpoint_name')

assert APP_SP_ID, "app_sp_id parameter is required"
assert ROUTER_ENDPOINT, "serving_endpoint_name parameter is required"

# Resolve SP numeric ID to application_id (UUID) for permissions API
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
sp = w.service_principals.get(id=APP_SP_ID)
APP_SP_APP_ID = sp.application_id

print(f"App SP application_id: {APP_SP_APP_ID} (numeric ID: {APP_SP_ID})")
print(f"Router Endpoint: {ROUTER_ENDPOINT}")
print(f"LLM Endpoint: {LLM_ENDPOINT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant Serving Endpoint Access
# MAGIC Grants CAN_QUERY on the router model endpoint and the LLM foundation model endpoint.

# COMMAND ----------

# DBTITLE 1,Grant serving endpoint access to app SP
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

def get_endpoint_id(endpoint_name: str) -> str:
    """Resolve serving endpoint name to its numeric ID."""
    ep = w.serving_endpoints.get(name=endpoint_name)
    return ep.id

def grant_endpoint_access(endpoint_name: str, sp_app_id: str):
    """Grant CAN_QUERY on a serving endpoint to the given SP."""
    # The permissions API requires the endpoint ID, not the name
    endpoint_id = get_endpoint_id(endpoint_name)
    print(f"  Resolved '{endpoint_name}' -> ID: {endpoint_id}")
    
    payload = {
        "access_control_list": [
            {
                "service_principal_name": sp_app_id,
                "permission_level": "CAN_QUERY",
            }
        ]
    }
    try:
        w.api_client.do(
            "PATCH",
            f"/api/2.0/permissions/serving-endpoints/{endpoint_id}",
            body=payload,
        )
        print(f"\u2713 Granted CAN_QUERY on '{endpoint_name}' to {sp_app_id}")
    except Exception as e:
        print(f"\u2717 Failed for '{endpoint_name}': {e}")
        raise

# Grant access to the router model endpoint
grant_endpoint_access(ROUTER_ENDPOINT, APP_SP_APP_ID)

# Grant access to the LLM foundation model endpoint (for parameter extraction)
if LLM_ENDPOINT:
    try:
        grant_endpoint_access(LLM_ENDPOINT, APP_SP_APP_ID)
    except Exception as e:
        # Foundation model endpoints may not support custom permissions
        print(f"\u2139 Skipping LLM endpoint permissions (foundation models are accessible by default): {e}")

# COMMAND ----------

# DBTITLE 1,Verify endpoint access
# Verify permissions on the router endpoint
def verify_endpoint_access(endpoint_name: str, sp_app_id: str):
    try:
        endpoint_id = get_endpoint_id(endpoint_name)
        resp = w.api_client.do(
            "GET",
            f"/api/2.0/permissions/serving-endpoints/{endpoint_id}",
        )
        acl = resp.get("access_control_list", [])
        for entry in acl:
            if entry.get("service_principal_name") == sp_app_id:
                perms = [p["permission_level"] for p in entry.get("all_permissions", [])]
                print(f"\u2705 Verified: {sp_app_id} has {perms} on '{endpoint_name}'")
                return True
        print(f"\u26a0\ufe0f {sp_app_id} not found in ACL for '{endpoint_name}'")
    except Exception as e:
        print(f"\u26a0\ufe0f Could not verify permissions for '{endpoint_name}': {e}")
    return False

verify_endpoint_access(ROUTER_ENDPOINT, APP_SP_APP_ID)

print("\n\u2705 Serving endpoint access setup complete")