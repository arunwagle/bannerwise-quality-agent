# Bannerwise Quality Agent

## Executive Summary

The Bannerwise Quality Agent is an AI-powered **Q&A governance system** for Banner Health's advertising analytics. It solves a critical enterprise challenge: **How do you let business users ask natural-language questions about data while ensuring answer accuracy and compliance?**

The system implements a **two-lane confidence gate** architecture:

* **Certified Lane** — Questions that match a pre-approved, SME-certified Q&A corpus are answered instantly using vetted SQL templates. These answers carry a "Certified" badge.
* **Analytical Lane** — Novel questions are routed to a Genie Space agent that generates SQL dynamically. These answers carry a "Not Certified" badge and can be submitted for SME review to enter the certified corpus.

This creates a **certification flywheel**: over time, more questions become certified, improving answer trust and reducing latency.

---

## Datasets

### Analytics Tables (9 tables)

Populated by the `create_synthetic_data` notebook with realistic advertising metrics.

| Table | Description |
| --- | --- |
| `ad_metrics` | Daily ad performance (impressions, clicks, spend, revenue) by campaign/period |
| `campaign_metrics` | Campaign-level aggregates (ROI, conversions, CPA) |
| `banner_performance` | Performance by banner size and creative |
| `regional_metrics` | Geographic breakdown (CPM, CTR by region) |
| `network_metrics` | Ad network comparison (Google, Meta, programmatic) |
| `channel_metrics` | Channel-level cost and acquisition metrics |
| `session_metrics` | User session data from banner click-through traffic |
| `creative_performance` | Creative variant A/B test results |
| `attribution_metrics` | Multi-touch attribution by channel |

### System Tables

| Table | Description | Populated By |
| --- | --- | --- |
| `certified_qa_corpus` | SME-approved question/SQL/answer templates (~20 entries) | `setup_test_data` notebook, then the certification flywheel |
| `certified_qa_corpus_draft` | Pending questions awaiting SME review | App "Add to SME Review" action |
| `query_history` | Audit log of every question asked through the app | App automatically on each query |
| `sme_review_queue` | Flagged queries for expert review | App "Flag Incorrect" action |
| `router_eval_dataset` / `router_eval_results` | Evaluation datasets and scored results | Eval pipeline notebooks |

All tables reside in **`aw_serverless_stable_catalog.bannerhealth`** and are managed via Unity Catalog.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Databricks App (Flask)                        │
│   Ask Page → /api/quality/assess                                    │
└──────────┬──────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Model Serving Endpoint     │  (bannerwise-quality-router)
│  ┌───────────────────────┐  │
│  │ 1. Vector Search      │──┼──► certified_qa_index (cosine similarity)
│  │ 2. LLM Judge          │──┼──► Evaluates semantic equivalence
│  │ 3. Confidence Gate    │  │   confidence >= 0.5 → Certified
│  └───────────────────────┘  │   confidence < 0.5  → Analytical
└──────────┬──────────────────┘
           │
     ┌─────┴──────┐
     ▼            ▼
┌──────────┐  ┌──────────────┐
│ Certified│  │  Genie Space │
│   Lane   │  │  (Analytical)│
├──────────┤  ├──────────────┤
│ Lookup   │  │ Generate SQL │
│ SQL tmpl │  │ dynamically  │
│ Extract  │  │ from 9 tables│
│ params   │  │              │
│ Execute  │  │ Execute      │
│ Format   │  │ Return answer│
└──────────┘  └──────────────┘
     │              │
     ▼              ▼
┌─────────────────────────────┐
│  Response to User           │
│  Badge: Certified / Not     │
│  + SQL + Provenance         │
└─────────────────────────────┘
```

---

## How Routing Works (with examples)

### Step 1: Vector Search
User's question is embedded and compared against the certified corpus via cosine similarity.

### Step 2: LLM Judge
The top candidate is evaluated by an LLM (Meta Llama 3.3 70B) for semantic equivalence.

### Step 3: Confidence Gate
If the judge says YES → confidence = 1.0 → **Certified Lane**.  
If the judge says NO → confidence = 0.0 → **Analytical Lane (Genie)**.

**Threshold:** `confidence >= 0.5` routes to certified lane.

### Example: Certified

> **User:** "What is the total ad spend for Q1 2025?"
>
> **VS Match:** QA-0001 — "What is the total ad spend for {period}?" (VS Score: 68%)
>
> **Judge:** YES — same intent, parameter = "Q1 2025"
>
> **Result:** Certified ✅ | SQL: `SELECT SUM(spend) FROM ad_metrics WHERE period = 'Q1 2025'` | Answer: "$254,500.75"

### Example: Analytical (correctly rejected)

> **User:** "Which campaign had the highest ROI this year?"
>
> **VS Match:** QA-0006 — "What was the ROI for the {campaign} campaign?" (VS Score: 69.6%)
>
> **Judge:** NO — different intent (ranking all campaigns vs. querying one specific campaign)
>
> **Result:** Not Certified ⚠️ | Routed to Genie → generates CTE with RANK() → Answer: "summer campaign, ROI 3.03"

---

## Evaluation Pipeline

The router is evaluated before deployment using:

* **Eval Dataset:** Generated from the certified corpus (positive matches + negative/paraphrased pairs)
* **Metrics:** Precision, recall, F1 for routing accuracy; latency benchmarks
* **Threshold Check:** Eval must pass minimum quality gates before model promotion
* **Judge Model:** `databricks-meta-llama-3-3-70b-instruct`

See [ROUTER_TEST_DESIGN.md](docs/ROUTER_TEST_DESIGN.md) for detailed evaluation methodology.

---

## Key Components

| Component | Technology | Purpose |
| --- | --- | --- |
| App | Databricks Apps (Flask + Gunicorn) | User-facing web interface |
| Router Model | MLflow PyFunc + Model Serving | Confidence gate routing logic |
| Vector Search | Databricks Vector Search (Delta Sync) | Semantic similarity matching |
| LLM Judge | Meta Llama 3.3 70B (Foundation Model) | Semantic equivalence evaluation |
| Genie Space | Databricks Genie | Dynamic SQL generation for analytical queries |
| Infrastructure | Declarative Automation Bundles (DABs) | Reproducible deployment |
| AI Gateway | Databricks AI Gateway | Rate limiting, inference logging |

---

## Getting Started

### Prerequisites

* Databricks workspace with Unity Catalog enabled
* Databricks CLI installed and authenticated (`databricks auth login`)
* A catalog and schema where you have CREATE TABLE + MODIFY permissions
* A SQL Warehouse (serverless recommended)
* Access to Foundation Model endpoints (`databricks-meta-llama-3-3-70b-instruct`, `databricks-bge-large-en`)

### Step 1 — Deploy the Bundle

```bash
cd bannerwise-quality-agent/bannerwise-app
databricks bundle deploy --target dev
```

This creates all DABs resources: jobs, Genie Space, app definition, and AI Gateway configuration.

### Step 2 — Run the Setup Job

Creates the schema, all tables (including the `embedding_text` column on `certified_qa_corpus`), and populates 9 analytics tables with synthetic data.

```bash
databricks bundle run setup_job --target dev
```

**Tables created:** `certified_qa_corpus`, `certified_qa_corpus_draft`, `query_history`, `sme_review_queue`, plus 9 analytics tables.

### Step 3 — Run the Vector Index Job

Creates the Vector Search Delta Sync index on `certified_qa_corpus`. The index embeds the `embedding_text` column (not `question`) using `databricks-bge-large-en` for better intent matching.

```bash
databricks bundle run vector_index_job --target dev
```

> **Note:** Wait for the index status to become ONLINE before proceeding (~2-5 minutes).

### Step 4 — Run the Router Agent Job

Trains the router agent (PyFunc model), runs the evaluation pipeline, registers the model in Unity Catalog, promotes to `@champion` alias, and deploys to the serving endpoint.

```bash
databricks bundle run router_agent_job --target dev
```

This job includes:
* Model training with `DatabricksVectorSearchIndex` + `DatabricksServingEndpoint` resource declarations
* Eval dataset generation + quality gate check
* Model registration + champion promotion
* Serving endpoint deployment + AI Gateway configuration

### Step 5 — Run the Access Job

Grants the app service principal all required permissions (UC, SQL Warehouse, VS endpoint, serving endpoints, Genie Space). All 4 tasks run in parallel.

> **Why last?** The access job grants permissions on the VS index and serving endpoint — these resources must exist first.

```bash
databricks bundle run setup_access_job --target dev
```

### Step 6 — Deploy the App

```bash
databricks apps deploy dev-bw-quality-agent --source-code-path bannerwise-app/apps
```

The app starts with Gunicorn (4 workers) and is accessible at its assigned URL.

### Step 7 — Verify End-to-End

1. Open the app URL
2. Ask: "What is the total ad spend for Q1 2025?"
3. Expected: **Certified** badge, answer "$254,500.75", provenance showing QA-0001

---

### Fresh Rebuild (Destroy + Redeploy)

To tear down everything and start fresh:

```bash
# Destroy existing resources
databricks bundle destroy --target dev --auto-approve

# Redeploy
databricks bundle deploy --target dev

# Run jobs in order
databricks bundle run setup_job --target dev
databricks bundle run vector_index_job --target dev
databricks bundle run router_agent_job --target dev
databricks bundle run setup_access_job --target dev

# Deploy app
databricks apps deploy dev-bw-quality-agent --source-code-path bannerwise-app/apps
```

> **Important:** After destroying and recreating the VS index, you must re-run `setup_access_job` — grants are lost when the index is deleted.

---

### Environment Variables (app.yaml)

| Variable | Value | Purpose |
| --- | --- | --- |
| `SERVING_ENDPOINT_NAME` | `bannerwise-quality-router` | Router model endpoint |
| `SQL_WAREHOUSE_ID` | `2d8e531640ffa469` | SQL execution backend |
| `CATALOG_NAME` | `aw_serverless_stable_catalog` | Unity Catalog catalog |
| `SCHEMA_NAME` | `bannerhealth` | Schema for all tables |
| `LLM_ENDPOINT` | `databricks-meta-llama-3-3-70b-instruct` | LLM for SQL correction + judge |
| `GENIE_SPACE_ID` | `01f19026d0e61c88b840ce168a9be672` | Genie Space for analytical lane |
| `API_MODE` | `live` | `live` (real endpoint) or `demo` (mock) |

---

## Further Reading

* [Solution Design](docs/SOLUTION_DESIGN.md) — Detailed technical architecture
* [Router Test Design](docs/ROUTER_TEST_DESIGN.md) — Evaluation methodology and test scenarios
* [Requirements](docs/REQUIREMENTS.md) — Functional and non-functional requirements
* [UI Requirements](docs/UI_REQUIREMENTS.md) — Frontend design specifications
* [Project Structure](docs/PROJECT_STRUCTURE.md) — File and folder layout
