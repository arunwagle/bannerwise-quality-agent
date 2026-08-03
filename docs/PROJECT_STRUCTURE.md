# Bannerwise Quality Agent — Project Structure

## Directory Layout

```
bannerwise-quality-agent/
├── docs/
│   ├── REQUIREMENTS.md          — Functional requirements (phases 1–3)
│   ├── SOLUTION_DESIGN.md       — Architecture, data model, decision flow
│   ├── UI_REQUIREMENTS.md       — Flask app UI specifications
│   ├── ROUTER_TEST_DESIGN.md    — Eval dataset design and test categories
│   └── PROJECT_STRUCTURE.md     — This file
│
└── bannerwise-app/              — DABs bundle root
    ├── databricks.yml           — Bundle config (targets: dev, prod)
    │
    ├── resources/
    │   ├── bannerwise_quality_agent.job.yml   — 4 jobs (setup, vector-index, router, eval)
    │   ├── bannerwise_quality_agent.ai.yml    — VS endpoint resource
    │   └── bannerwise_quality_agent.app.yml   — App resource (disabled, managed outside bundle)
    │
    ├── notebooks/
    │   ├── create_tables.py              — DDL for corpus, history, review queue
    │   ├── create_synthetic_data.py      — Analytics tables (ad_metrics, campaign_metrics, etc.)
    │   ├── create_vector_search_index.py — Creates Delta Sync VS index on certified_qa_corpus
    │   ├── grant_permissions.py          — Grants SP access to warehouse, endpoints, UC
    │   ├── router_agent.py               — Router agent definition (MLflow Pyfunc)
    │   ├── register_router_model.py      — Register router model to UC
    │   ├── deploy_serving_endpoint.py    — Deploy model to serving endpoint
    │   ├── configure_ai_gateway.py       — AI Gateway config (inference tables, rate limits)
    │   ├── generate_eval_dataset.py      — LLM-generated eval dataset from corpus
    │   ├── run_router_eval_v2.py         — Router evaluation (mapInPandas + batch judge)
    │   └── check_eval_thresholds.py      — Quality gate assertions (precision/recall)
    │
    ├── tests/notebooks/
    │   └── setup_test_data.py            — Populates certified QA corpus with synthetic data
    │
    └── apps/                             — Flask web application
        ├── app.py                        — Flask app factory
        ├── app.yaml                      — Gunicorn config + env vars (API_MODE, etc.)
        ├── config.py                     — Environment-based config classes
        ├── gunicorn.conf.py              — Gunicorn worker settings
        ├── requirements.txt              — Python dependencies
        ├── routes/
        │   └── quality_routes.py         — /api/quality/assess endpoint
        ├── services/
        │   ├── live_router_service.py    — Calls serving endpoint + certified lane
        │   ├── certified_lane_service.py — SQL execution for certified answers
        │   ├── mock_router_service.py    — Static mock responses (dev mode)
        │   ├── mock_corpus_service.py    — Mock corpus data
        │   └── mock_history_service.py   — Mock query history
        ├── models/                       — Data models
        ├── middleware/                   — Auth middleware
        ├── templates/                    — Jinja2 HTML templates
        └── static/                       — CSS, JS assets
```

---

## Bundle Resources

### Jobs (defined in `bannerwise_quality_agent.job.yml`)

| Job | Purpose | Tasks |
| --- | --- | --- |
| **setup_job** | Infrastructure setup | `grant_app_permissions` → `create_schema_and_tables` → `create_analytics_tables` |
| **vector_index_job** | Corpus + VS index | `setup_certified_corpus` → `create_vector_search_index` |
| **router_agent_job** | Full deploy pipeline | `run_router_agent` → `run_eval` → `register_model` → `deploy_serving_endpoint` → `configure_ai_gateway` |
| **eval_job** | Pre-deploy quality gate | `generate_eval_dataset` → `run_router_eval` → `check_eval_thresholds` |

### AI Resources (defined in `bannerwise_quality_agent.ai.yml`)

| Resource | Type | Notes |
| --- | --- | --- |
| `bannerwise_vs_endpoint` | Vector Search Endpoint (STANDARD) | Created by bundle |
| `certified_qa_index` | Delta Sync Index | Created by `vector_index_job` (commented out in YAML) |

### App (defined in `bannerwise_quality_agent.app.yml`)

| Resource | Notes |
| --- | --- |
| `aw-bannerwise-quality-agent` | Managed outside bundle (pre-existing); disabled in YAML |

---

## Deployment Order

For a clean deployment from scratch:

```
1. bundle deploy --target dev
   └── Creates: VS endpoint, 4 jobs

2. Run setup_job
   └── Creates: schema, tables, analytics data, grants SP permissions

3. Run vector_index_job
   └── Populates corpus → creates VS index (depends on tables from step 2)

4. Run router_agent_job
   └── Smoke test → eval → register model → deploy endpoint → AI gateway

5. Deploy app (via SDK or bundle if bound)
   └── App connects to serving endpoint and SQL warehouse
```

---

## Key Configuration

| Parameter | Value | Used By |
| --- | --- | --- |
| `catalog_name` | `aw_serverless_stable_catalog` | All jobs |
| `schema_name` | `bannerhealth` | All jobs |
| `vs_endpoint` | `bannerwise-vs-endpoint` | Router, eval |
| `sql_warehouse_id` | `2d8e531640ffa469` | Eval, app |
| `judge_model` | `databricks-meta-llama-3-3-70b-instruct` | Router, eval |
| `confidence_threshold` | `0.5` | Router, eval |
| `serving_endpoint` | `bannerwise-quality-router` | App, router job |
| `embedding_model` | `databricks-bge-large-en` | VS index |

---

## App Environment Variables (app.yaml)

| Variable | Value | Purpose |
| --- | --- | --- |
| `API_MODE` | `live` | Use live serving endpoint (not mock) |
| `SERVING_ENDPOINT_NAME` | `bannerwise-quality-router` | Router model endpoint |
| `SQL_WAREHOUSE_ID` | `2d8e531640ffa469` | Certified lane SQL execution |
| `CATALOG_NAME` | `aw_serverless_stable_catalog` | Corpus table location |
| `SCHEMA_NAME` | `bannerhealth` | Corpus table schema |
| `LLM_ENDPOINT` | `databricks-meta-llama-3-3-70b-instruct` | Parameter extraction |

---

## Service Principal

| Field | Value |
| --- | --- |
| Name | `app-3hjyzw aw-bannerwise-quality-agent` |
| SP ID | `75518798649324` |
| OAuth client_id | `91fd799e-f466-4486-a85a-3150e0faa552` |

**Required permissions** (granted by `grant_permissions.py`):
- CAN_USE on SQL Warehouse
- CAN_QUERY on Serving Endpoints (router + LLM)
- USE CATALOG, USE SCHEMA, SELECT on UC tables
