# Bannerwise Quality Agent — Solution Design

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                    BannerWise Databricks App                        │
│                  (Flask + Gunicorn on DB Apps)                      │
└────────────────────────────────┬───────────────────────────────────┘
                                 │ User Prompt
                                 ▼
┌────────────────────────────────────────────────────────────────────┐
│              CONFIDENCE GATE (Model Serving Endpoint)               │
│                                                                    │
│   embed → Vector Search retrieve (top-k) → LLM Judge →            │
│   confidence score (0.0 or 1.0 based on judge verdict)             │
└────────────────────────────────┬───────────────────────────────────┘
                                 │
                        confidence >= 0.5
                        AND status = certified?
                                 │
                  ┌──── YES ─────┴───── NO ────┐
                  ▼                            ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│ CERTIFIED LANE            │    │ ANALYTICAL LANE            │
│ (green)                   │    │ (amber)                    │
│                           │    │                            │
│ • Lookup SQL template     │    │ • Route to Genie Space     │
│ • Extract params via LLM  │    │   Conversation API         │
│ • Execute certified SQL   │    │ • Dynamic SQL generation   │
│ • Format answer via LLM   │    │ • Returns table/text       │
│                           │    │                            │
│ → Badge: "Certified"      │    │ → Badge: "Not Certified"   │
│ + provenance              │    │ + "Add to SME Review"      │
└──────────────────────────┘    └──────────────────────────┘
```

---

## Supporting Layers

### Layer 1 — Governed Semantic Layer

| Component | Purpose |
| --- | --- |
| UC Tables (9 analytics tables) | Source data for Genie Space queries |
| SQL Warehouse | Execution engine for certified SQL and Genie-generated SQL |
| Genie Space (DABs resource) | Powers the Analytical Lane with schema-aware SQL generation |

### Layer 2 — Certified Q&A Corpus

| Component | Purpose |
| --- | --- |
| `certified_qa_corpus` (Delta, CDF enabled) | Stores question + parameterized SQL + answer template |
| `certified_qa_corpus_draft` (Delta) | Staging table for pending SME reviews |
| Vector Search Delta Sync Index | Auto-syncs embeddings from the corpus table |

### Layer 3 — Confidence Gate (Router Agent)

| Step | Operation |
| --- | --- |
| Embed | Convert user prompt to vector (databricks-bge-large-en) |
| Retrieve | Query `certified_qa_index` for top-k candidates (k=3) |
| Judge | LLM evaluates semantic equivalence (YES/NO) |
| Gate | If judge says YES → confidence=1.0 → Certified Lane |
|      | If judge says NO → confidence=0.0 → Analytical Lane |

### Layer 4 — Governance & Audit

| Component | Purpose |
| --- | --- |
| `query_history` table | Every request logged with lane, confidence, SQL, latency |
| AI Gateway | Rate limiting + inference table logging |
| Provenance | Each response includes corpus_id, VS score, judge verdict, SQL |

---

## Router Agent Design

> **Pattern**: MLflow PyFunc model served via Model Serving.  
> The router always calls Vector Search first, then uses an LLM judge to determine if the match is semantically equivalent. This is a fixed pipeline — not dynamic tool selection.

### Decision Flow

```
                          User Prompt
                              │
                              ▼
                    ┌─────────────────┐
                    │  1. RETRIEVE     │
                    │                  │
                    │  Embed prompt →  │
                    │  Query VS Index  │
                    │  (top-k = 3)     │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  2. LLM JUDGE    │
                    │                  │
                    │  "Does user Q    │
                    │   have same      │
                    │   intent as      │
                    │   corpus Q?"     │
                    │                  │
                    │  → YES or NO     │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  3. GATE         │
                    │     DECISION    │
                    │                  │
                    │  Judge=YES →     │
                    │  conf=1.0        │
                    │                  │
                    │  Judge=NO →      │
                    │  conf=0.0        │
                    │                  │
                    │  conf >= 0.5?    │
                    └───┬─────────┬────┘
                        │         │
                   YES  │         │  NO
                        ▼         ▼
           ┌────────────────┐   ┌──────────────────────┐
           │  CERTIFIED     │   │  ANALYTICAL LANE     │
           │  LANE          │   │  (Genie Space)       │
           └────────────────┘   └──────────────────────┘
```

### Step Details

#### Step 1 — Retrieve

| Aspect | Detail |
| --- | --- |
| Input | User prompt (raw text) |
| Operation | Embed via `databricks-bge-large-en`, query `certified_qa_index` with `top_k=3` |
| Output | List of candidates: `{corpus_id, question, score, status, parameterized_sql, answer_template, parameters}` |

#### Step 2 — LLM Judge

| Aspect | Detail |
| --- | --- |
| Purpose | Determine if the user's question has the same intent as the matched corpus question |
| Model | `databricks-meta-llama-3-3-70b-instruct` |
| Output | YES (same intent) or NO (different intent) |
| Example YES | User: "What is the total ad spend for Q1 2025?" ↔ Corpus: "What is the total ad spend for {period}?" |
| Example NO | User: "Which campaign had the highest ROI?" ↔ Corpus: "What was the ROI for the {campaign} campaign?" |

#### Step 3 — Gate Decision

| Judge Verdict | Confidence | Lane | Badge |
| --- | --- | --- | --- |
| YES | 1.0 | Certified | "Certified" |
| NO | 0.0 | Analytical | "Not Certified" |

**Threshold:** `0.5` (configurable via `CONFIDENCE_THRESHOLD` env var)

---

## Certified Lane — Execution Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    CERTIFIED LANE                              │
│                                                              │
│  1. Lookup corpus entry by corpus_id                          │
│  2. Extract parameters from prompt via LLM                    │
│  3. Bind parameters into parameterized_sql template           │
│  4. Execute SQL via SQL Warehouse (statement_execution API)   │
│  5. Format answer using LLM + answer_template                 │
│  6. Return with badge: "Certified"                            │
└──────────────────────────────────────────────────────────────┘
```

## Analytical Lane — Execution Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    ANALYTICAL LANE (Genie Space)               │
│                                                              │
│  1. POST /api/2.0/genie/spaces/{id}/start-conversation       │
│     Body: {"content": "<user_prompt>"}                        │
│                                                              │
│  2. Poll GET .../messages/{id} until COMPLETED or timeout     │
│                                                              │
│  3. Extract: generated SQL, answer text from attachments      │
│                                                              │
│  4. Return with badge: "Not Certified"                        │
│     + provenance: {genie_status, sql_executed, genie_error}  │
│                                                              │
│  5. User can click "Add to SME Review" to submit for         │
│     certification flywheel                                   │
└──────────────────────────────────────────────────────────────┘
```

---

## Certification Flywheel

```
User asks question → Analytical Lane (Not Certified)
       │
       ▼
Clicks "Add to SME Review"
       │
       ▼
Draft saved to certified_qa_corpus_draft table
       │
       ▼
SME opens Review page → sees question + SQL + answer
       │
       ├── "Run Modified Query" → test/edit SQL, see results
       │
       ├── "Certify" → moves to certified_qa_corpus → VS index auto-syncs
       │                              │
       │           Next similar question → Certified Lane ✅
       │
       └── "Reject" → removed from draft table
```

---

## Flask Application Services

| Service | File | Purpose |
| --- | --- | --- |
| `live_router_service.py` | Router (live) | Calls Model Serving endpoint, dispatches to certified/analytical lane |
| `demo_router_service.py` | Router (demo) | Offline demo mode — no serving endpoint needed |
| `certified_lane_service.py` | Certified execution | Lookup SQL, extract params via LLM, execute, format answer |
| `genie_service.py` | Genie integration | Genie Space Conversation API (start, poll, extract) |
| `corpus_service.py` | Corpus/Drafts CRUD | Submit drafts, certify, reject, list pending reviews |
| `history_service.py` | Query logging | Log every query to `query_history` Delta table, read stats |

### Service Selection (API_MODE)

| Mode | `API_MODE` env var | Service | When |
| --- | --- | --- | --- |
| Live | `live` | `live_router_service.py` | Deployed app (calls Model Serving) |
| Demo | `mock` | `demo_router_service.py` | Local dev, UI prototyping |

---

## Configuration Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `CONFIDENCE_THRESHOLD` | `0.5` | Gate threshold (judge YES=1.0 passes, NO=0.0 fails) |
| `VS_TOP_K` | `3` | Number of candidates from Vector Search |
| `JUDGE_MODEL` | `databricks-meta-llama-3-3-70b-instruct` | LLM for semantic equivalence evaluation |
| `GENIE_SPACE_ID` | `01f19026d0e61c88b840ce168a9be672` | Genie Space for analytical lane |
| `GENIE_TIMEOUT_SEC` | `60` | Max wait for Genie response |
| `SQL_WAREHOUSE_ID` | `2d8e531640ffa469` | Warehouse for certified SQL execution |
| `SERVING_ENDPOINT_NAME` | `bannerwise-quality-router` | Model Serving endpoint name |
| `LLM_ENDPOINT` | `databricks-meta-llama-3-3-70b-instruct` | LLM for param extraction + answer formatting |

---

## Deployment Architecture (DABs)

```
bannerwise-app/                        (Bundle Root)
├── databricks.yml                      engine: direct, targets: dev/prod
│
├── resources/
│   ├── bannerwise_quality_agent.job.yml    (6 jobs)
│   ├── bannerwise_quality_agent.ai.yml     (VS endpoint)
│   ├── bannerwise_quality_agent.app.yml    (Flask app)
│   └── bannerwise_quality_agent.genie.yml  (Genie Space resource)
│
├── src/genie/
│   └── bannerwise_analytics.geniespace.json  (9 tables, 15 examples)
│
├── notebooks/
│   ├── data/       (create_tables, create_synthetic_data, cleanup)
│   ├── vs/         (create_vector_search_index, cleanup)
│   ├── agent/      (router_agent, register, deploy, configure_gateway)
│   ├── eval/       (generate_eval_dataset, run_eval, check_thresholds)
│   └── access/     (setup_uc_access, setup_vs_access, setup_endpoint_access, setup_genie_access)
│
└── apps/                               (Flask source_code_path)
    ├── app.py, config.py, gunicorn.conf.py
    ├── app.yaml (env vars including GENIE_SPACE_ID)
    ├── routes/     (quality, history, corpus, admin, health)
    ├── services/   (live_router, demo_router, certified_lane, genie, corpus, history)
    ├── templates/  (ask, demo, history, corpus, admin, layout)
    └── static/     (css, js)
```

### 6 Deployment Jobs

| Job | Purpose | Key Tasks |
| --- | --- | --- |
| `setup_job` | Create schema + tables | create_tables → create_synthetic_data |
| `setup_access_job` | Grant app SP permissions | UC access, VS access, endpoint access, Genie access |
| `vector_index_job` | Build VS index | create_vector_search_index |
| `router_agent_job` | Train + deploy router | router_agent → eval → register → deploy → AI Gateway |
| `eval_job` | Evaluate router quality | generate_eval → run_eval → check_thresholds |
| `cleanup_job` | Tear down resources | VS index, serving endpoint, model, schema |

---

## Data Model

### certified_qa_corpus

```sql
CREATE TABLE certified_qa_corpus (
    id                  STRING NOT NULL,
    question            STRING NOT NULL,
    question_embedding  ARRAY<FLOAT>,
    parameterized_sql   STRING NOT NULL,
    answer_template     STRING NOT NULL,
    parameters          ARRAY<STRING>,
    status              STRING,          -- certified | draft | expired
    certified_by        STRING,
    certified_date      TIMESTAMP,
    next_review_date    DATE NOT NULL,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP
) TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
```

### certified_qa_corpus_draft

```sql
CREATE TABLE certified_qa_corpus_draft (
    id                  STRING NOT NULL,  -- DRAFT-{8hex}
    question            STRING,
    parameterized_sql   STRING,
    answer_template     STRING,
    parameters          STRING,
    submitted_by        STRING,
    original_prompt     STRING,
    created_at          TIMESTAMP
)
```

### query_history

```sql
CREATE TABLE query_history (
    id              STRING NOT NULL,     -- H-{uuid[:8]}
    user_email      STRING,
    prompt          STRING,
    lane            STRING,              -- certified | analytical
    confidence      FLOAT,
    badge           STRING,              -- Certified | Not Certified
    corpus_id       STRING,
    sql_executed    STRING,
    answer          STRING,
    latency_ms      INT,
    timestamp       TIMESTAMP
)
```

---

## Key Resource IDs

| Resource | ID / Name |
| --- | --- |
| SQL Warehouse | `2d8e531640ffa469` |
| VS Endpoint | `bannerwise-vs-endpoint` |
| VS Index | `aw_serverless_stable_catalog.bannerhealth.certified_qa_index` |
| Serving Endpoint | `bannerwise-quality-router` |
| Registered Model | `aw_serverless_stable_catalog.bannerhealth.bannerwise_quality_router` |
| Genie Space | `01f19026d0e61c88b840ce168a9be672` |
| App (dev) | `dev-bw-quality-agent` |
| App SP | `26659230-2dcc-4c45-acdf-f907aeba6eec` |
| LLM Endpoint | `databricks-meta-llama-3-3-70b-instruct` |

---

## Security & Access Control

| Concern | Approach |
| --- | --- |
| App Authentication | Databricks App service principal (OAuth M2M) |
| UC Permissions | GRANT USE CATALOG, USE SCHEMA, SELECT, MODIFY to app SP |
| SQL Safety | Only SELECT queries allowed in run-query endpoint; parameterized SQL in certified lane |
| Genie Access | CAN_RUN granted to app SP via `/api/2.0/permissions/genie/{id}` |
| VS Access | CAN_USE on VS endpoint granted to app SP |
| Serving Access | CAN_QUERY on serving + LLM endpoints |
| Warehouse Access | CAN_USE on SQL warehouse |

---

## Further Reading

* [Router Test Design](ROUTER_TEST_DESIGN.md) — Evaluation methodology, test scenarios, metrics
* [Requirements](REQUIREMENTS.md) — Functional and non-functional requirements
* [UI Requirements](UI_REQUIREMENTS.md) — Frontend design specifications
* [Project Structure](PROJECT_STRUCTURE.md) — File and folder layout
