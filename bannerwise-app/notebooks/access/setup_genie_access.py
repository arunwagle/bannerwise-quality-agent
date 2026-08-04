# Databricks notebook source
# DBTITLE 1,Setup Genie Space Access
# MAGIC %md
# MAGIC # Setup Genie Space Access
# MAGIC Grants the app service principal `CAN_RUN` permission on the Genie Space.

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text('app_sp_id', '')
dbutils.widgets.text('genie_space_id', '')

APP_SP_ID = dbutils.widgets.get('app_sp_id')
GENIE_SPACE_ID = dbutils.widgets.get('genie_space_id')

assert APP_SP_ID, "app_sp_id parameter is required"
assert GENIE_SPACE_ID, "genie_space_id parameter is required"

# Resolve SP numeric ID to application_id (UUID)
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()
sp = w.service_principals.get(id=APP_SP_ID)
APP_SP_APP_ID = sp.application_id

print(f"App SP application_id: {APP_SP_APP_ID} (numeric ID: {APP_SP_ID})")
print(f"Genie Space ID: {GENIE_SPACE_ID}")

# COMMAND ----------

# DBTITLE 1,Grant CAN_RUN on Genie Space
payload = {
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
        f"/api/2.0/permissions/dashboards/{GENIE_SPACE_ID}",
        body=payload,
    )
    print(f"\u2713 Granted CAN_RUN on Genie Space {GENIE_SPACE_ID} to {APP_SP_APP_ID}")
except Exception as e:
    print(f"\u26a0\ufe0f Could not grant via dashboards API: {e}")
    print("Trying genie/spaces permissions path...")
    try:
        w.api_client.do(
            "PATCH",
            f"/api/2.0/permissions/genie/spaces/{GENIE_SPACE_ID}",
            body=payload,
        )
        print(f"\u2713 Granted CAN_RUN on Genie Space {GENIE_SPACE_ID} to {APP_SP_APP_ID}")
    except Exception as e2:
        raise RuntimeError(f"Failed to grant Genie Space access: {e2}")

print("\n\u2705 Genie Space access setup complete")

# COMMAND ----------

