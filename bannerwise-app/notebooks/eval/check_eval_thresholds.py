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

# DBTITLE 1,Configuration — Layered Gates
dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")
# Layer 1: VS Retrieval (embedding_text target)
dbutils.widgets.text("min_vs_retrieval", "0.80")
# Layer 2: Judge Accuracy
dbutils.widgets.text("min_judge_precision", "0.90")
dbutils.widgets.text("min_judge_recall", "0.85")
# Layer 3: End-to-End
dbutils.widgets.text("min_gate_precision", "0.85")
dbutils.widgets.text("min_adjusted_recall", "0.80")
# Control
dbutils.widgets.text("fail_on_gate_miss", "true")

CATALOG = dbutils.widgets.get("catalog_name")
SCHEMA = dbutils.widgets.get("schema_name")
MIN_VS_RETRIEVAL = float(dbutils.widgets.get("min_vs_retrieval"))
MIN_JUDGE_PRECISION = float(dbutils.widgets.get("min_judge_precision"))
MIN_JUDGE_RECALL = float(dbutils.widgets.get("min_judge_recall"))
MIN_GATE_PRECISION = float(dbutils.widgets.get("min_gate_precision"))
MIN_ADJUSTED_RECALL = float(dbutils.widgets.get("min_adjusted_recall"))
FAIL_ON_GATE_MISS = dbutils.widgets.get("fail_on_gate_miss").lower() == "true"

print(f"Layered Deployment Gate Thresholds:")
print(f"  Layer 1 — VS Retrieval Accuracy:  >= {MIN_VS_RETRIEVAL}")
print(f"  Layer 2 — Judge Precision:         >= {MIN_JUDGE_PRECISION}")
print(f"  Layer 2 — Judge Recall:            >= {MIN_JUDGE_RECALL}")
print(f"  Layer 3 — Gate Precision:          >= {MIN_GATE_PRECISION}")
print(f"  Layer 3 — Adjusted Recall:         >= {MIN_ADJUSTED_RECALL}")
print(f"  Fail on miss: {FAIL_ON_GATE_MISS}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Read Metrics from Upstream Task

# COMMAND ----------

# DBTITLE 1,Read Layered Metrics from Upstream Task
# Read layered metrics from run_router_eval
# Layer 1: VS Retrieval
vs_retrieval_accuracy = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="vs_retrieval_accuracy", default=0.0)
retrieval_rate = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="retrieval_hit_rate", default=0.0)
# Layer 2: Judge
judge_precision = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="judge_precision", default=0.0)
judge_recall = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="judge_recall", default=0.0)
# Layer 3: End-to-End
precision = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="gate_precision", default=0.0)
recall = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="gate_recall", default=0.0)
staleness_adjusted_recall = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="staleness_adjusted_recall", default=0.0)
f1 = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="f1_score", default=0.0)
# Advisory
staleness = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="staleness_enforcement", default=0.0)
near_miss_rate = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="near_miss_rejection_rate", default=0.0)
adversarial_rate = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="adversarial_rejection_rate", default=0.0)
latency_p95 = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="latency_p95_ms", default=0)
total_rows = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="total_eval_rows", default=0)
fp_count = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="false_positive_count", default=0)
fn_count = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="false_negative_count", default=0)
mlflow_run_id = dbutils.jobs.taskValues.get(taskKey="run_router_eval", key="mlflow_run_id", default="")

print(f"Metrics from run_router_eval (Layered):")
print(f"  --- Layer 1: VS Retrieval ---")
print(f"  VS Retrieval Accuracy:  {vs_retrieval_accuracy}")
print(f"  Retrieval Hit Rate:     {retrieval_rate}")
print(f"  --- Layer 2: Judge ---")
print(f"  Judge Precision:        {judge_precision}")
print(f"  Judge Recall:           {judge_recall}")
print(f"  --- Layer 3: End-to-End ---")
print(f"  Gate Precision:         {precision}")
print(f"  Gate Recall (raw):      {recall}")
print(f"  Adjusted Recall:        {staleness_adjusted_recall}")
print(f"  F1 Score:               {f1}")
print(f"  --- Advisory ---")
print(f"  Staleness Enforcement:  {staleness}")
print(f"  Near-Miss Rejection:    {near_miss_rate}")
print(f"  Adversarial Rejection:  {adversarial_rate}")
print(f"  Latency P95:            {latency_p95}ms")
print(f"  Total Eval Rows:        {total_rows}")
print(f"  FP: {fp_count}, FN: {fn_count}")
print(f"  MLflow Run ID:          {mlflow_run_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evaluate Deployment Gates

# COMMAND ----------

# DBTITLE 1,Evaluate Layered Deployment Gates
gate_results = []

# Layered deployment gates
gates = [
    # Layer 1: VS Retrieval (the embedding_text improvement target)
    ("L1: VS Retrieval Accuracy", vs_retrieval_accuracy, MIN_VS_RETRIEVAL, "Layer 1"),
    # Layer 2: Judge Accuracy
    ("L2: Judge Precision",       judge_precision,       MIN_JUDGE_PRECISION, "Layer 2"),
    ("L2: Judge Recall",          judge_recall,          MIN_JUDGE_RECALL, "Layer 2"),
    # Layer 3: End-to-End
    ("L3: Gate Precision",        precision,             MIN_GATE_PRECISION, "Layer 3"),
    ("L3: Adjusted Recall",       staleness_adjusted_recall, MIN_ADJUSTED_RECALL, "Layer 3"),
]

print("╔══════════════════════════════════════════════════════════════╗")
print("║  LAYERED DEPLOYMENT GATE EVALUATION                          ║")
print("╠══════════════════════════════════════════════════════════════╣")

all_passed = True
current_layer = ""
for name, actual, target, layer in gates:
    if layer != current_layer:
        current_layer = layer
        print(f"║  --- {layer} {'─'*(52 - len(layer))} ║")
    passed = actual >= target
    status = "PASS ✓" if passed else "FAIL ✗"
    if not passed:
        all_passed = False
    gate_results.append({"metric": name, "actual": actual, "target": target, "layer": layer, "passed": passed})
    print(f"║  {name:<27} {actual:.4f}  (>= {target:.2f})  {status:<8} ║")

print("╠══════════════════════════════════════════════════════════════╣")

# Advisory metrics (informational, don't block)
advisory = [
    ("Near-Miss Rejection",   near_miss_rate,   0.85),
    ("Adversarial Rejection",  adversarial_rate, 0.90),
    ("Staleness Enforcement",  staleness,        1.00),
    ("Latency P95",            latency_p95/5000, 1.0),
]

print("║  --- Advisory (informational) ──────────────────────────── ║")
for name, actual, target in advisory:
    status = "OK" if actual >= target else "WARN"
    if name == "Latency P95":
        print(f"║  {name:<27} {latency_p95}ms     (< 5000ms)    {status:<8} ║")
    else:
        print(f"║  {name:<27} {actual:.4f}  (>= {target:.2f})    {status:<8} ║")

print("╠══════════════════════════════════════════════════════════════╣")

# Final verdict
if all_passed:
    print("║                                                              ║")
    print("║  >>> ALL GATES PASSED <<<                                    ║")
    print("║  Router is cleared for deployment.                           ║")
    print("║                                                              ║")
else:
    failed_layers = sorted(set(g["layer"] for g in gate_results if not g["passed"]))
    print("║                                                              ║")
    print("║  >>> DEPLOYMENT BLOCKED <<<                                  ║")
    print(f"║  Failed: {', '.join(failed_layers):<50} ║")
    print("║                                                              ║")

print("╚══════════════════════════════════════════════════════════════╝")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Failure Details

# COMMAND ----------

# DBTITLE 1,Failure Details and Recommendations
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

    # Recommendations based on layered gates
    print(f"\n  RECOMMENDED ACTIONS:")
    print(f"  {'─'*56}")
    if vs_retrieval_accuracy < MIN_VS_RETRIEVAL:
        print(f"  • L1 VS retrieval low ({vs_retrieval_accuracy:.3f} < {MIN_VS_RETRIEVAL}): improve embedding_text generation or add more phrasings")
    if judge_precision < MIN_JUDGE_PRECISION:
        print(f"  • L2 Judge precision low ({judge_precision:.3f} < {MIN_JUDGE_PRECISION}): tighten judge prompt rules for false matches")
    if judge_recall < MIN_JUDGE_RECALL:
        print(f"  • L2 Judge recall low ({judge_recall:.3f} < {MIN_JUDGE_RECALL}): relax judge prompt for valid paraphrases/synonyms")
    if precision < MIN_GATE_PRECISION:
        print(f"  • L3 Gate precision low ({precision:.3f} < {MIN_GATE_PRECISION}): raise confidence_threshold or improve judge prompt")
    if staleness_adjusted_recall < MIN_ADJUSTED_RECALL:
        print(f"  • L3 Adjusted recall low ({staleness_adjusted_recall:.3f} < {MIN_ADJUSTED_RECALL}): lower confidence_threshold or improve VS embeddings")
    if near_miss_rate < 0.85:
        print(f"  • Near-miss rejection low ({near_miss_rate:.3f}): judge is over-matching semantically close questions")
    if adversarial_rate < 0.90:
        print(f"  • Adversarial rejection low ({adversarial_rate:.3f}): add adversarial awareness to judge prompt")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assert and Exit
# MAGIC
# MAGIC This cell **FAILS the notebook** (and thus the job task) if gates are not met.

# COMMAND ----------

# DBTITLE 1,Assert and Exit
import json

result = {
    "status": "PASSED" if all_passed else "FAILED",
    "layers": {
        "layer_1_vs_retrieval": vs_retrieval_accuracy,
        "layer_2_judge_precision": judge_precision,
        "layer_2_judge_recall": judge_recall,
        "layer_3_gate_precision": precision,
        "layer_3_adjusted_recall": staleness_adjusted_recall,
    },
    "failed_gates": [g["metric"] for g in gate_results if not g["passed"]],
    "mlflow_run_id": mlflow_run_id,
}

if all_passed:
    print("\n All layered deployment gates PASSED. Router is ready for deployment.")
    dbutils.notebook.exit(json.dumps(result))
else:
    failed_names = ', '.join(result['failed_gates'])
    print(f"\n Deployment gates NOT MET: {failed_names}")
    if FAIL_ON_GATE_MISS:
        raise Exception(json.dumps(result))
    else:
        print("  fail_on_gate_miss=false — job will NOT fail. Review results above.")
        dbutils.notebook.exit(json.dumps(result))