# Databricks notebook source
# MAGIC %md
# MAGIC # Cleanup Schema
# MAGIC Drops the schema and all tables/views within it.

# COMMAND ----------

dbutils.widgets.text('catalog_name', 'aw_serverless_stable_catalog')
dbutils.widgets.text('schema_name', 'bannerhealth')

CATALOG = dbutils.widgets.get('catalog_name')
SCHEMA = dbutils.widgets.get('schema_name')

print(f"Target: {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## List tables before drop

# COMMAND ----------

tables_df = spark.sql(f"SHOW TABLES IN `{CATALOG}`.`{SCHEMA}`")
display(tables_df)
print(f"Found {tables_df.count()} table(s) in {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Drop schema CASCADE
# MAGIC This removes all tables, views, and the schema itself.

# COMMAND ----------

spark.sql(f"DROP SCHEMA IF EXISTS `{CATALOG}`.`{SCHEMA}` CASCADE")
print(f"\u2713 Dropped schema {CATALOG}.{SCHEMA} (CASCADE)")

# COMMAND ----------

# Verify schema is gone
try:
    spark.sql(f"DESCRIBE SCHEMA `{CATALOG}`.`{SCHEMA}`")
    print(f"\u26a0 Schema {CATALOG}.{SCHEMA} still exists!")
except Exception as e:
    print(f"\u2705 Confirmed: schema {CATALOG}.{SCHEMA} no longer exists")
