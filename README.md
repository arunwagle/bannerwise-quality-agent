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

## Deployment

The entire project is deployed via DABs (`bundle deploy --target dev`):

1. **Setup Job** — Creates schema, tables, and synthetic data
2. **Access Job** — Grants permissions to the app service principal
3. **Vector Index Job** — Builds the vector search index from certified corpus
4. **Router Job** — Trains, evaluates, registers, and deploys the router model
5. **Genie Space** — Deployed as a DABs resource (9 analytics tables)
6. **App** — Deployed as a Databricks App with environment variables

---

## Further Reading

* [Solution Design](docs/SOLUTION_DESIGN.md) — Detailed technical architecture
* [Router Test Design](docs/ROUTER_TEST_DESIGN.md) — Evaluation methodology and test scenarios
* [Requirements](docs/REQUIREMENTS.md) — Functional and non-functional requirements
* [UI Requirements](docs/UI_REQUIREMENTS.md) — Frontend design specifications
* [Project Structure](docs/PROJECT_STRUCTURE.md) — File and folder layout
