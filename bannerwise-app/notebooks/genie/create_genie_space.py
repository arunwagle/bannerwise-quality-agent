# Databricks notebook source
# DBTITLE 1,Create Genie Space
# MAGIC %md
# MAGIC # Create or Update Genie Space
# MAGIC
# MAGIC Reads the serialized_space configuration from the previous task and calls the Genie Space API to create (or update) the space.
# MAGIC
# MAGIC **Parameters:**
# MAGIC - `space_id`: Set to empty string to CREATE, or existing ID to UPDATE

# COMMAND ----------

# DBTITLE 1,Parameters
dbutils.widgets.text("space_id", "")  # Empty = create new, existing ID = update

SPACE_ID = dbutils.widgets.get("space_id").strip()
print(f"Mode: {'UPDATE ' + SPACE_ID if SPACE_ID else 'CREATE new space'}")

# COMMAND ----------

# DBTITLE 1,Read config from previous task
import json

# Read output from build_genie_config task
task_output = dbutils.jobs.taskValues.get(
    taskKey="build_genie_config",
    key="return_value",
    debugValue='{"space_title": "DEBUG", "space_description": "DEBUG", "warehouse_id": "2d8e531640ffa469", "serialized_space": "{}"}'
)

config = json.loads(task_output)
SPACE_TITLE = config["space_title"]
SPACE_DESCRIPTION = config["space_description"]
WAREHOUSE_ID = config["warehouse_id"]
SERIALIZED_SPACE = config["serialized_space"]

print(f"Title: {SPACE_TITLE}")
print(f"Description: {SPACE_DESCRIPTION[:100]}...")
print(f"Warehouse: {WAREHOUSE_ID}")
print(f"Config size: {len(SERIALIZED_SPACE):,} chars")

# COMMAND ----------

# DBTITLE 1,Create or Update Genie Space
import requests

def get_workspace_url():
    return spark.conf.get("spark.databricks.workspaceUrl")

def get_api_headers():
    token = (
        dbutils.notebook.entry_point.getDbutils()
        .notebook().getContext().apiToken().get()
    )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

ws_url = get_workspace_url()
headers = get_api_headers()

# Determine parent path for new spaces
user_email = spark.conf.get("spark.databricks.notebook.path").split("/")[3]
parent_path = f"/Users/{user_email}"

if SPACE_ID:
    # UPDATE existing
    print(f"Updating space {SPACE_ID}...")
    resp = requests.patch(
        f"https://{ws_url}/api/2.0/genie/spaces/{SPACE_ID}",
        headers=headers,
        json={
            "title": SPACE_TITLE,
            "description": SPACE_DESCRIPTION,
            "serialized_space": SERIALIZED_SPACE,
        },
    )
else:
    # CREATE new
    print(f"Creating new Genie space...")
    resp = requests.post(
        f"https://{ws_url}/api/2.0/genie/spaces",
        headers=headers,
        json={
            "title": SPACE_TITLE,
            "description": SPACE_DESCRIPTION,
            "warehouse_id": WAREHOUSE_ID,
            "parent_path": parent_path,
            "serialized_space": SERIALIZED_SPACE,
        },
    )

# Report result
if resp.status_code == 200:
    result = resp.json()
    space_id = result.get("space_id", SPACE_ID)
    print(f"\n\u2705 SUCCESS")
    print(f"   Space ID    : {space_id}")
    print(f"   Title       : {result.get('title')}")
    print(f"   Description : {result.get('description', '')[:120]}")
    if not SPACE_ID:
        print(f"\n\u26a0\ufe0f  Save this ID for future updates:")
        print(f'   space_id = "{space_id}"')
    # Return space ID for downstream use
    dbutils.notebook.exit(json.dumps({"space_id": space_id, "status": "success"}))
else:
    err = resp.json()
    error_msg = f"Genie API error ({resp.status_code}): {err.get('error_code')} - {err.get('message', '')[:200]}"
    print(f"\n\u274c FAILED")
    print(f"   {error_msg}")
    raise RuntimeError(error_msg)

# COMMAND ----------

