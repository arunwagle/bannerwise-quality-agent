# Databricks notebook source
# MAGIC %md
# MAGIC # Check Evaluation Thresholds — Deployment Gate
# MAGIC 
# MAGIC Reads metrics from `run_router_eval` task values and asserts they meet deployment gates.
# MAGIC **FAILS the job** if primary metrics are below targets.
# MAGIC 
# MAGIC See `docs/ROUTER_TEST_DESIGN.md` §3.1 for threshold rationale.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")
dbutils.widgets.text("min_precision", "0.95")
dbutils.widgets.text("min_recall", "0.80")
dbutils.widgets.text("min_f1", "0.87")
dbutils.widgets.text("min_staleness", "1.00")

CATALOG = dbutils.widgets.get("catalog_name")
SCHEMA = dbutils.widgets.get("schema_name")
MIN_PRECISION = float(dbutils.widgets.get("min_precision"))
MIN_RECALL = float(dbutils.widgets.get("min_recall"))
MIN_F1 = float(dbutils.widgets.get("min_f1"))
MIN_STALENESS = float(dbutils.widgets.get("min_staleness"))

print(f"Deployment Gate Thresholds:")
print(f"  Min Precision:  {MIN_PRECISION}")
print(f"  Min Recall:     {MIN_RECALL}")
print(f"  Min F1:         {MIN_F1}")
print(f"  Min Staleness:  {MIN_STALENESS}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Metrics from Upstream Task

# COMMAND ----------

# Read task values from run_router_eval
precision = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="gate_precision", default=0.0)
recall = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="gate_recall", default=0.0)
f1 = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="f1_score", default=0.0)
staleness = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="staleness_enforcement", default=0.0)
near_miss_rate = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="near_miss_rejection_rate", default=0.0)
adversarial_rate = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="adversarial_rejection_rate", default=0.0)
retrieval_rate = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="retrieval_hit_rate", default=0.0)
latency_p95 = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="latency_p95_ms", default=0)
total_rows = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="total_eval_rows", default=0)
fp_count = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="false_positive_count", default=0)
fn_count = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="false_negative_count", default=0)
mlflow_run_id = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="mlflow_run_id", default="")

print(f"Metrics from run_router_eval:")
print(f"  Gate Precision:         {precision}")
print(f"  Gate Recall:            {recall}")
print(f"  F1 Score:               {f1}")
print(f"  Staleness Enforcement:  {staleness}")
print(f"  Near-Miss Rejection:    {near_miss_rate}")
print(f"  Adversarial Rejection:  {adversarial_rate}")
print(f"  Retrieval Hit Rate:     {retrieval_rate}")
print(f"  Latency P95:            {latency_p95}ms")
print(f"  Total Eval Rows:        {total_rows}")
print(f"  False Positives:        {fp_count}")
print(f"  False Negatives:        {fn_count}")
print(f"  MLflow Run ID:          {mlflow_run_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evaluate Deployment Gates

# COMMAND ----------

gate_results = []

# Primary gates (block deployment)
gates = [
    ("Gate Precision",       precision, MIN_PRECISION,  ">="),
    ("Gate Recall",          recall,    MIN_RECALL,     ">="),
    ("F1 Score",             f1,        MIN_F1,         ">="),
    ("Staleness Enforcement", staleness, MIN_STALENESS, ">="),
]

print("╔══════════════════════════════════════════════════════════════╗")
print("║  DEPLOYMENT GATE EVALUATION                                  ║")
print("╠══════════════════════════════════════════════════════════════╣")

all_passed = True
for name, actual, target, op in gates:
    passed = actual >= target
    status = "PASS ✓" if passed else "FAIL ✗"
    if not passed:
        all_passed = False
    gate_results.append({"metric": name, "actual": actual, "target": target, "passed": passed})
    print(f"║  {name:<25} {actual:.4f}  (target: {op} {target:.2f})  {status:<8} ║")

print("╠══════════════════════════════════════════════════════════════╣")

# Secondary metrics (advisory)
advisory = [
    ("Near-Miss Rejection",  near_miss_rate,   0.90),
    ("Adversarial Rejection", adversarial_rate, 0.95),
    ("Retrieval Hit Rate",   retrieval_rate,    0.95),
    ("Latency P95",          latency_p95/5000,  1.0),  # Normalized: < 5000ms = pass
]

print("║  --- Advisory Metrics (informational) ---                    ║")
for name, actual, target in advisory:
    status = "OK" if actual >= target else "WARN"
    if name == "Latency P95":
        print(f"║  {name:<25} {latency_p95}ms  (target: < 5000ms)    {status:<8} ║")
    else:
        print(f"║  {name:<25} {actual:.4f}  (target: >= {target:.2f})    {status:<8} ║")

print("╠══════════════════════════════════════════════════════════════╣")

# Final verdict
if all_passed:
    print("║                                                              ║")
    print("║  >>> DEPLOYMENT GATE: PASSED <<<                             ║")
    print("║  Router is cleared for model registration and deployment.    ║")
    print("║                                                              ║")
else:
    print("║                                                              ║")
    print("║  >>> DEPLOYMENT GATE: FAILED <<<                             ║")
    print("║  Router does NOT meet quality thresholds.                    ║")
    print("║  Deployment is blocked.                                      ║")
    print("║                                                              ║")

print("╚══════════════════════════════════════════════════════════════╝")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Failure Details

# COMMAND ----------

if not all_passed:
    # Read the results table for failure details
    results_df = spark.table(f"{CATALOG}.{SCHEMA}.router_eval_results")
    
    # Show false positives (most critical)
    fps = results_df.filter(
        (results_df.expected_lane == "analytical") & (results_df.predicted_lane == "certified")
    ).orderBy(results_df.predicted_confidence.desc())
    
    fp_count_actual = fps.count()
    if fp_count_actual > 0:
        print(f"\n  FALSE POSITIVES ({fp_count_actual} cases):")
        print(f"  {'─'*56}")
        for row in fps.collect()[:10]:
            print(f"  [{row['eval_id']}] category={row['category']}")
            print(f"    Prompt: {row['prompt'][:90]}")
            print(f"    Confidence: {row['predicted_confidence']:.3f}, matched: {row['predicted_corpus_id']}")
            print()
    
    # Show false negatives (moderate concern)
    fns = results_df.filter(
        (results_df.expected_lane == "certified") & (results_df.predicted_lane == "analytical")
    ).orderBy(results_df.predicted_confidence.desc())
    
    fn_count_actual = fns.count()
    if fn_count_actual > 0:
        print(f"\n  FALSE NEGATIVES ({fn_count_actual} cases):")
        print(f"  {'─'*56}")
        for row in fns.collect()[:10]:
            print(f"  [{row['eval_id']}] category={row['category']}")
            print(f"    Prompt: {row['prompt'][:90]}")
            print(f"    Confidence: {row['predicted_confidence']:.3f}")
            print()

    # Recommendations
    print(f"\n  RECOMMENDED ACTIONS:")
    print(f"  {'─'*56}")
    if precision < MIN_PRECISION:
        print(f"  • Gate precision too low ({precision:.3f} < {MIN_PRECISION}): raise confidence_threshold or improve judge prompt")
    if recall < MIN_RECALL:
        print(f"  • Gate recall too low ({recall:.3f} < {MIN_RECALL}): lower confidence_threshold or improve VS embeddings")
    if staleness < MIN_STALENESS:
        print(f"  • Staleness enforcement failed: check staleness_check logic in router_agent")
    if near_miss_rate < 0.90:
        print(f"  • Near-miss rejection low ({near_miss_rate:.3f}): judge is over-matching semantically close questions")
    if adversarial_rate < 0.95:
        print(f"  • Adversarial rejection low ({adversarial_rate:.3f}): add adversarial awareness to judge prompt")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assert and Exit
# MAGIC 
# MAGIC This cell **FAILS the notebook** (and thus the job task) if gates are not met.

# COMMAND ----------

if all_passed:
    print("All deployment gates passed. Router is ready for deployment.")
    dbutils.notebook.exit(json.dumps({
        "status": "PASSED",
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "staleness": staleness,
        "mlflow_run_id": mlflow_run_id
    }))
else:
    failed_gates = [g["metric"] for g in gate_results if not g["passed"]]
    error_msg = f"DEPLOYMENT GATE FAILED: {', '.join(failed_gates)}"
    print(f"\n{error_msg}")
    
    # Raise an exception to FAIL the job task
    import json
    raise Exception(json.dumps({
        "status": "FAILED",
        "error": error_msg,
        "failed_gates": failed_gates,
        "metrics": {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "staleness": staleness
        },
        "mlflow_run_id": mlflow_run_id,
        "action_required": "Review false positives and tune threshold or judge prompt"
    }))
