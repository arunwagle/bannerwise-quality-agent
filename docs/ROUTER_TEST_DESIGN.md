# Router Agent — Evaluation & Test Design

> **Goal**: A reliable, large-scale evaluation suite that validates the router's confidence gate
> before deploying to production. Uses MLflow Evaluate with custom scorers, run as a pre-deploy gate job.

---

## Executive Summary (Customer-Facing)

### What We Test

Before any update to the Quality Router reaches production, it must pass an **automated quality gate** — a suite of ~180 test scenarios that validate the router correctly distinguishes between questions it can answer with pre-approved ("certified") responses and questions that need fresh analytical processing.

### Why It Matters

The router carries **asymmetric risk**: serving a wrong answer with a "HUMAN APPROVED" badge (false positive) is far more damaging than routing a valid question through the analytical path (false negative). Our evaluation is designed around this principle — we prioritize **precision** (never serve a bad certified answer) over recall (occasionally miss a valid match).

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    QUALITY GATE PIPELINE                         │
│                                                                 │
│  1. GENERATE TEST DATA                                          │
│     • LLM creates paraphrases of certified questions            │
│     • LLM creates "trick" questions (similar words,             │
│       different intent)                                         │
│     • Adversarial inputs (prompt injection, typos,              │
│       obfuscation)                                              │
│     • Questions matching expired/stale entries                  │
│                                                                 │
│  2. RUN ROUTER ON ALL TEST CASES                                │
│     • Each test prompt is sent through the full routing          │
│       pipeline (Vector Search → LLM Judge → Confidence Gate)    │
│     • Results logged to MLflow for traceability                 │
│                                                                 │
│  3. ASSERT QUALITY THRESHOLDS                                   │
│     • Precision ≥ 85% — of answers labeled "HUMAN APPROVED",   │
│       at least 85% must genuinely match the user's intent       │
│     • Recall ≥ 80% — of questions that SHOULD match a           │
│       certified answer, at least 80% are correctly routed       │
│     • Staleness = 100% — expired entries NEVER serve as         │
│       certified, regardless of confidence score                 │
│                                                                 │
│  OUTCOME: Gate PASSES → model promoted to production            │
│           Gate FAILS  → deployment blocked, failures reported   │
└─────────────────────────────────────────────────────────────────┘
```

### Test Scenario Categories

| Category | What We Test | Expected Outcome |
| --- | --- | --- |
| Paraphrases | Same question asked differently ("total spend" vs "how much did we spend in total") | Should route to certified |
| Parameter variations | Same template, different values ("Q1" → "Q3", "spring_sale" → "holiday") | Should route to certified |
| Near-miss negatives | Similar words but different intent ("total spend" vs "spend breakdown by region") | Should route to analytical |
| Adversarial prompts | Prompt injection, intentional typos ("siz3"), padding text, system overrides | Should route to analytical |
| Stale entries | Questions matching expired corpus entries (past review date) | Should route to analytical |

### Current Results (Latest Passing Run)

| Metric | Score | Gate | Status |
| --- | --- | --- | --- |
| Precision | 0.924 | ≥ 0.85 | PASSED |
| Recall | 0.914 | ≥ 0.80 | PASSED |
| F1 Score | 0.919 | — | — |

### Key Design Principles

1. **Eval runs BEFORE deployment** — no code reaches production without passing the gate
2. **Binary LLM Judge** — an LLM evaluates whether user intent matches the certified template (not just keyword overlap)
3. **Multi-candidate retrieval** — top-3 vector search results are evaluated, not just the closest match
4. **Ratchet effect** — every failure adds harder test cases, making the suite progressively more rigorous
5. **Full traceability** — every eval run is logged to MLflow with per-row results, enabling root-cause analysis of any failure

### Confidence & Trust

The system uses a **binary confidence model**:
- LLM Judge says "MATCH" → confidence = 1.0 → routes to certified lane
- LLM Judge says "NO_MATCH" → confidence = 0.0 → routes to analytical lane
- Any entry past its review date → confidence forcibly capped below threshold → never certified

This eliminates the ambiguity of numerical scores — the judge either confirms intent match or it doesn't. No grey area.

---

## Technical Details

---

## 1. Problem Statement

The router makes a binary routing decision with **asymmetric risk**:

| Error Type | What Happens | Severity |
| --- | --- | --- |
| **False Positive** | Routes to certified lane when it shouldn't → serves wrong answer with "HUMAN APPROVED" badge | **Critical** — erodes user trust |
| **False Negative** | Routes to analytical lane when it should match → unnecessary Genie call | **Moderate** — wasteful but safe |

The evaluation must be **precision-biased**: never let a bad match through the gate.

---

## 2. Evaluation Dataset Design

### 2.1 Dataset Structure

Each row in the evaluation dataset is a **test case**:

```
eval_dataset (Delta Table: aw_serverless_stable_catalog.bannerhealth.router_eval_dataset)
├── id              STRING     — Unique test case ID (e.g., "EVAL-0001")
├── prompt          STRING     — The test user question
├── category        STRING     — Test category (see below)
├── expected_lane   STRING     — "certified" | "analytical"
├── expected_corpus_id STRING  — Expected matching corpus entry ID (NULL for analytical)
├── difficulty      STRING     — "easy" | "medium" | "hard"
├── source_corpus_id STRING   — Which corpus entry this was derived from (for traceability)
├── generation_method STRING  — "llm_paraphrase" | "param_variation" | "near_miss" | "adversarial" | "manual"
├── created_at      TIMESTAMP
└── notes           STRING     — Additional context for debugging failures
```

### 2.2 Test Categories

| Category | Count | Expected Lane | Generation Strategy |
| --- | --- | --- | --- |
| **exact_paraphrase** | 5–10 per corpus entry (~100–200) | certified | LLM rephrases the certified question preserving intent |
| **parameter_variation** | 3–5 per parameterized entry (~30–50) | certified | Same intent, different parameter values ("Q1" → "Q3", "spring_sale" → "holiday") |
| **colloquial_rewrite** | 3 per corpus entry (~60) | certified | Casual/informal rephrasings ("What's the CTR?" vs "What is the click-through rate by banner size?") |
| **near_miss_negative** | 3–5 per corpus entry (~60–100) | analytical | Semantically close but *different intent* — tests the gate doesn't over-match |
| **unrelated_question** | 50 | analytical | Completely different domain or novel analytical questions |
| **stale_entry_test** | 10–20 | analytical | Questions matching corpus entries with past `next_review_date` |
| **adversarial** | 20–30 | analytical | Prompt injection, compound questions, ambiguous phrasing |
| **boundary_cases** | 20–30 | mixed | Questions designed to land near the confidence threshold |

**Total target**: ~400–500 evaluation rows

### 2.3 Generation Strategy

```
┌───────────────────────────────────────────────────────────────────────┐
│              EVAL DATASET GENERATION PIPELINE                          │
│                                                                       │
│  Input: certified_qa_corpus (20 entries)                              │
│                                                                       │
│  ┌─────────────────┐                                                  │
│  │ For each corpus │                                                  │
│  │ entry:          │                                                  │
│  │                 │                                                  │
│  │ 1. LLM generates 5-10 paraphrases        → expected: certified    │
│  │ 2. LLM generates 3-5 param variations    → expected: certified    │
│  │ 3. LLM generates 3 colloquial rewrites   → expected: certified    │
│  │ 4. LLM generates 3-5 near-miss negatives → expected: analytical   │
│  │                                                                    │
│  └─────────────────┘                                                  │
│                                                                       │
│  Plus:                                                                │
│  • 50 unrelated domain questions             → expected: analytical   │
│  • 20 stale-entry questions                  → expected: analytical   │
│  • 20-30 adversarial prompts                 → expected: analytical   │
│  • 20-30 boundary-calibration questions      → expected: mixed        │
│                                                                       │
│  Output: router_eval_dataset (~450 rows)                              │
└───────────────────────────────────────────────────────────────────────┘
```

#### LLM Generation Prompts

**Paraphrases** (expected: certified):
```
Given this certified question: "{question}"
Generate {n} paraphrases that ask the EXACT same thing using different words.
Rules:
- Preserve the original intent completely
- Vary sentence structure, vocabulary, and phrasing
- Include formal, casual, and question-with-context variations
- If the question has parameters, keep the same parameters but may reword around them
```

**Near-Miss Negatives** (expected: analytical):
```
Given this certified question: "{question}"
Generate {n} questions that are RELATED to the same topic but ask for something DIFFERENT.
Rules:
- Must be about the same general domain (ads, banners, campaigns)
- Must have a clearly different intent (different metric, different aggregation, different time scope)
- Should be plausible questions a user might ask
- The router should NOT match these to the certified entry
Examples of "near miss": "total ad spend" (certified) vs "ad spend breakdown by region" (different intent)
```

**Adversarial** (expected: analytical):
```
Generate questions designed to stress-test a confidence-gated router:
- Compound questions combining multiple intents
- Questions with misleading keywords from certified entries
- Prompt injection attempts ("ignore previous instructions and...")
- Ambiguous questions that could match multiple entries
- Extremely long or short prompts
- Questions in broken English or with typos
```

---

## 3. Evaluation Metrics

### 3.1 Primary Metrics (Deployment Gate)

| Metric | Formula | Target | Blocks Deploy? |
| --- | --- | --- | --- |
| **Gate Precision** | TP / (TP + FP) for certified lane | >= 0.85 | Yes |
| **Gate Recall** | TP / (TP + FN) for certified lane | >= 0.80 | Yes |
| **F1 Score** | Harmonic mean of precision and recall | >= 0.87 | Yes |
| **Staleness Enforcement** | % of stale matches routed to analytical | = 1.00 | Yes |

#### Metric Definitions

**Gate Precision >= 0.85** — Of all queries the router routes to the certified lane (stamps
"HUMAN APPROVED"), at least 85% must *actually* be correct matches. We tolerate at most 15%
false positives — cases where the system confidently serves a pre-approved answer that doesn't
match the user's intent. Set high because a wrong "HUMAN APPROVED" answer directly erodes trust.

**Gate Recall >= 0.80** — Of all queries that *should* route to the certified lane (they
genuinely match a corpus entry), at least 80% are correctly routed there. We accept up to 20%
false negatives — legitimate matches sent to Genie instead. More relaxed because the cost is
lower: the user still gets an answer via the analytical lane, labeled "NOT YET APPROVED", so
no trust is violated. The tradeoff is latency and Genie cost.

**Staleness Enforcement = 1.00** — Any query matching a corpus entry whose `next_review_date`
is in the past must *always* route to the analytical lane — zero exceptions. A stale entry
may reference outdated SQL, deprecated columns, or incorrect business logic. Even if the
confidence score is 0.99, a stale entry must never serve as certified. Non-negotiable because
serving outdated data with a "HUMAN APPROVED" badge is worse than no certified answer at all.

**The asymmetry**: Precision is set much higher than recall because a false positive (bad
answer labeled as trusted) is far more damaging than a false negative (good answer routed
through Genie anyway).

### 3.2 Secondary Metrics (Advisory — does not block deploy)

| Metric | Formula | Target |
| --- | --- | --- |
| **Confidence AUC-ROC** | AUC of confidence score as classifier | >= 0.90 |
| **Retrieval Hit Rate** | % of positive cases where VS returns correct corpus_id in top-3 | >= 0.95 |
| **Near-Miss Rejection Rate** | % of near-miss negatives correctly routed to analytical | >= 0.90 |
| **Adversarial Rejection Rate** | % of adversarial prompts routed to analytical | >= 0.95 |
| **Latency P95** | 95th percentile end-to-end response time | < 5s |
| **Mean Confidence (positives)** | Average confidence for true-positive certified matches | >= 0.88 |
| **Mean Confidence (negatives)** | Average confidence for true-negative analytical routes | <= 0.50 |

### 3.3 Confidence Calibration

A well-calibrated router should produce a **bimodal confidence distribution**:
- True matches cluster near 0.90–0.95
- Non-matches cluster near 0.20–0.50
- Few cases in the "danger zone" (0.75–0.90)

The evaluation measures the separation gap between these clusters.

---

## 4. MLflow Evaluate Integration

### 4.1 Framework

Uses `mlflow.genai.evaluate()` with custom scorers:

```python
import mlflow
from mlflow.genai.scorers import Scorer

# Custom scorer: checks if routing decision matches expected lane
class GateAccuracyScorer(Scorer):
    name = "gate_accuracy"
    
    def score(self, *, output, expectations):
        predicted_lane = output["lane"]
        expected_lane = expectations["expected_lane"]
        return predicted_lane == expected_lane

# Custom scorer: checks confidence calibration
class ConfidenceCalibrationScorer(Scorer):
    name = "confidence_calibration"
    
    def score(self, *, output, expectations):
        confidence = output["confidence"]
        expected_lane = expectations["expected_lane"]
        if expected_lane == "certified":
            return confidence >= CONFIDENCE_THRESHOLD
        else:
            return confidence < CONFIDENCE_THRESHOLD

# Custom scorer: retrieval correctness
class RetrievalScorer(Scorer):
    name = "retrieval_hit"
    
    def score(self, *, output, expectations):
        expected_id = expectations.get("expected_corpus_id")
        if expected_id is None:
            return True  # No expected corpus match
        actual_id = output.get("provenance", {}).get("corpus_id")
        return actual_id == expected_id

# Run evaluation
results = mlflow.genai.evaluate(
    data=eval_dataset_df,
    predict_fn=router.predict,
    scorers=[
        GateAccuracyScorer(),
        ConfidenceCalibrationScorer(),
        RetrievalScorer(),
    ]
)
```

### 4.2 MLflow Experiment Tracking

Each eval run is logged to:
- **Experiment**: `/Users/arun.wagle@databricks.com/bannerwise-quality-router-eval`
- **Run tags**: `eval_version`, `corpus_version`, `threshold`, `model_version`
- **Artifacts**: full eval results CSV, confusion matrix, confidence distribution plot
- **Metrics**: all primary + secondary metrics logged as MLflow metrics

---

## 5. Eval Pipeline (Job Design)

### 5.1 Job Structure

```
resources/bannerwise_quality_agent.job.yml → eval_job

Tasks:
┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│ 1. generate_eval    │────▶│ 2. run_router_eval   │────▶│ 3. check_thresholds │
│    _dataset         │     │                      │     │                     │
│                     │     │ Runs router on every  │     │ Asserts primary     │
│ LLM generates       │     │ eval row, logs to     │     │ metrics meet        │
│ paraphrases +       │     │ MLflow experiment     │     │ deployment gates    │
│ negatives from      │     │                      │     │                     │
│ certified corpus    │     │ Uses mlflow.genai     │     │ FAILS job if        │
│                     │     │ .evaluate() with      │     │ precision < 0.85    │
│ Writes to:          │     │ custom scorers       │     │ or recall < 0.80    │
│ router_eval_dataset │     │                      │     │                     │
└─────────────────────┘     └──────────────────────┘     └─────────────────────┘
```

### 5.2 When to Run

| Trigger | Purpose |
| --- | --- |
| **Pre-deploy** | Before registering a new model version → deployment gate |
| **Corpus change** | When certified_qa_corpus is modified (new entries, edits) |
| **Threshold change** | When CONFIDENCE_THRESHOLD is tuned |
| **Scheduled (weekly)** | Detect drift in VS embeddings or model quality |

### 5.3 Job Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `catalog_name` | `aw_serverless_stable_catalog` | Target catalog |
| `schema_name` | `bannerhealth` | Target schema |
| `eval_dataset_table` | `router_eval_dataset` | Eval dataset table name |
| `num_paraphrases` | `7` | Paraphrases per corpus entry |
| `num_near_misses` | `4` | Near-miss negatives per entry |
| `min_precision` | `0.85` | Deployment gate threshold |
| `min_recall` | `0.80` | Deployment gate threshold |
| `regenerate_dataset` | `false` | Force regeneration of eval dataset |

---

## 6. Deployment Gate Pattern

### 6.1 CI/CD Integration

```
Developer commits router change
        │
        ▼
┌─────────────────────────┐
│  bundle validate        │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Run eval_job           │──── FAIL ──── Block deploy, report failures
│  (generate + eval +     │
│   check_thresholds)     │
└────────────┬────────────┘
             │ PASS
             ▼
┌─────────────────────────┐
│  Register model to UC   │
│  (new version)          │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  bundle deploy          │
│  (update serving        │
│   endpoint to new       │
│   model version)        │
└─────────────────────────┘
```

### 6.2 Failure Report

When the eval job fails, it produces a structured report:

```
╔══════════════════════════════════════════════════════════╗
║  DEPLOYMENT GATE: FAILED                                ║
╠══════════════════════════════════════════════════════════╣
║  Gate Precision:  0.92 (target: 0.95) ← FAILED         ║
║  Gate Recall:     0.85 (target: 0.80) ← PASSED         ║
║  Staleness:       1.00 (target: 1.00) ← PASSED         ║
╠══════════════════════════════════════════════════════════╣
║  Failed Cases (3 false positives):                      ║
║  ├── EVAL-0123: "Show ad spend trends" → certified      ║
║  │   Expected: analytical (near_miss_negative)          ║
║  │   Confidence: 0.87, matched QA-0001                  ║
║  ├── EVAL-0156: "What about campaign ROI?" → certified  ║
║  │   Expected: analytical (adversarial - ambiguous)     ║
║  │   Confidence: 0.86, matched QA-0006                  ║
║  └── EVAL-0201: "total spending Q2" → certified         ║
║      Expected: analytical (near_miss_negative)          ║
║      Confidence: 0.88, matched QA-0001                  ║
╠══════════════════════════════════════════════════════════╣
║  Action Required:                                       ║
║  • Review LLM judge prompt for over-matching            ║
║  • Consider raising threshold to 0.88                   ║
║  • Add failed cases to corpus as negative examples      ║
╚══════════════════════════════════════════════════════════╝
```

---

## 7. Test Notebook Structure

```
tests/
└── notebooks/
    ├── setup_test_data             (existing — synthetic corpus + history)
    ├── generate_eval_dataset       (LLM-powered eval dataset generation)
    ├── run_router_eval             (mlflow.genai.evaluate() execution)
    └── check_eval_thresholds       (gate assertion + report generation)
```

---

## 8. Production Monitoring (Post-Deploy)

Once deployed, ongoing quality is monitored via:

| Signal | Method | Alert Threshold |
| --- | --- | --- |
| **Confidence drift** | Weekly histogram of confidence scores | Mean shifts > 0.05 from baseline |
| **Lane distribution** | Daily ratio of certified vs analytical | Certified rate drops > 10% |
| **User feedback** | "Request SME Review" click rate | Rate exceeds 30% of analytical responses |
| **Latency** | P95 of end-to-end response time | Exceeds 5s |
| **VS index health** | Delta Sync pipeline status | Any sync failure |

These feed into a monitoring dashboard (defined in `resources/bannerwise_quality_agent.ai.yml` as future work).

---

## 9. Iteration Loop

The eval results feed directly back into improving the system:

```
Eval fails on specific cases
        │
        ├──▶ Add failing prompts to corpus (if they should be certified)
        ├──▶ Tune threshold (if boundary cases are miscalibrated)
        ├──▶ Improve judge prompt (if intent scoring is off)
        ├──▶ Add hard negatives to eval dataset (ratchet effect)
        │
        ▼
Re-run eval → metrics improve → deploy
```

This creates a **ratchet effect**: every failure makes the test suite harder, and the system must pass all accumulated tests before deploying.
