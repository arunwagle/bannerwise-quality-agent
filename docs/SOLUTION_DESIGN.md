# Bannerwise Quality Agent — Solution Design

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                    BannerWise Databricks App                        │
│                  (Flask + Gunicorn on DB Apps)                      │
└────────────────────────────┬───────────────────────────────────────┘
                             │ User Prompt
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│              TIER 3 — Deterministic Confidence Gate                 │
│                                                                    │
│   embed → Vector Search retrieve → rerank → CALIBRATE →           │
│   confidence % (deterministic — not an LLM decision)               │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                    confidence >= 0.85
                    AND status = certified?
                             │
              ┌──── YES ─────┴───── NO ────┐
              ▼                            ▼
┌──────────────────────┐    ┌──────────────────────────┐
│ STATE 1              │    │ STATE 2                    │
│ Certified Lane       │    │ Analytical Lane            │
│ (green)              │    │ (amber)                    │
│                      │    │                            │
│ • Extract params     │    │ • Route to Genie           │
│   via allow-list     │    │   Conversation API         │
│ • Run certified SQL  │    │ • Dynamic SQL synthesis    │
│ • Render SME answer  │    │ • Forecast / significance  │
│   template           │    │   for complex asks         │
│                      │    │                            │
│ → HUMAN APPROVED     │    │ → NOT YET APPROVED         │
│ + provenance         │    │ + "Request SME Review"     │
└──────────────────────┘    └──────────────────────────┘
```

---

## Supporting Tiers

### TIER 1 — Governed Semantic Layer

| Component | Purpose |
| --- | --- |
| UC Tables + Metric Views | One definition per quality metric |
| SQL Warehouse | Execution engine for certified SQL |
| Genie Space | Powers the Analytical Lane; certified SQL sits on this layer |

### TIER 2 — Certified Q&A Corpus

| Component | Purpose |
| --- | --- |
| UC Delta Table | Stores question + parameterized SQL + provenance |
| Vector Search Delta Sync Index | Auto-syncs embeddings from the corpus table |

### TIER 3 — Deterministic Confidence Gate

| Step | Operation |
| --- | --- |
| Embed | Convert user prompt to vector |
| Retrieve | Query `certified_qa_index` for top-k candidates |
| Rerank | LLM judge scores intent alignment (0–100) |
| Calibrate | Normalize + linear shrink to prevent over-confidence |
| Staleness check | Cap confidence if `next_review_date` is past |
| Gate | Compare against threshold (default 0.85) |

### TIER 5 — Governance

| Component | Purpose |
| --- | --- |
| MLflow Tracing | Records branch taken, confidence, SQL, sources for every request |
| Staleness Demotion | Entries past `next_review_date` automatically demoted below threshold |

---

## Supervisor Agent Design

> **Pattern**: [Multi-Agent Supervisor](https://docs.databricks.com/aws/en/agents/agent-bricks/multi-agent-supervisor)  
> The router is implemented as a **Supervisor Agent** that orchestrates two tools — Vector Search (deterministic retrieval) and Genie Space (LLM-powered analytics) — through a confidence-gated decision flow.

> **Critical invariant**: Vector Search is **always** invoked first for every user query. The Genie Space tool is only invoked as a fallback when the confidence gate determines the VS result is insufficient. This is a fixed sequential pipeline — not a dynamic LLM-driven tool selection.

### Agent Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       SUPERVISOR AGENT                                   │
│              (BannerwiseQualityRouter — MLflow Pyfunc)                   │
│                                                                         │
│   Deployed via: resources/bannerwise_quality_agent.ai.yml               │
│   Orchestrates tools in a FIXED sequential pipeline:                    │
│   Vector Search is ALWAYS called first → Gate → Genie only on fallback  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  TOOL 1 (ALWAYS FIRST) │
                    │  Vector Search         │
                    │  certified_qa_index    │
                    │                        │
                    │  Endpoint: bannerwise- │
                    │  vs-endpoint (STANDARD)│
                    └───────────┬────────────┘
                                │
                         confidence >= 0.85?
                                │
                    ┌───── YES ──┴── NO ─────┐
                    │                        │
                    ▼                        ▼
           ┌────────────────┐    ┌────────────────────┐
           │  Certified     │    │  TOOL 2 (FALLBACK) │
           │  Lane          │    │  Genie Space       │
           │  (State 1)     │    │  Conversation API  │
           │                │    │  (State 2)         │
           └────────────────┘    └────────────────────┘
```

### Tools

| Tool | Type | Purpose | Invocation |
| --- | --- | --- | --- |
| **Vector Search** | Deterministic retrieval | Find nearest certified Q&A pair for the user's prompt | `vector_search_indexes.query_index()` |
| **Genie Space** | LLM generative | Synthesize SQL + answer for novel analytical questions | Genie Conversation API (`/api/2.0/genie/spaces/{id}/conversations`) |

### Decision Flow (Step-by-Step)

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
                    │  2. SHORT-CIRCUIT│
                    │     CHECK       │
                    │                  │     No candidates OR
                    │  Candidates      │───── VS call failed ──────┐
                    │  returned?       │                            │
                    └────────┬─────────┘                            │
                             │ Yes                                  │
                             ▼                                      │
                    ┌─────────────────┐                             │
                    │  3. RERANK /     │                             │
                    │     CALIBRATE   │                             │
                    │                  │                             │
                    │  Pick top-1      │                             │
                    │  candidate       │                             │
                    │                  │                             │
                    │  LLM Judge:      │                             │
                    │  "Same intent?"  │                             │
                    │  → raw 0–100     │                             │
                    │                  │                             │
                    │  Normalize →     │                             │
                    │  [0.0, 1.0]      │                             │
                    │                  │                             │
                    │  Linear shrink:  │                             │
                    │  conf = raw *    │                             │
                    │  shrink_factor   │                             │
                    └────────┬─────────┘                             │
                             │                                      │
                             ▼                                      │
                    ┌─────────────────┐                             │
                    │  4. STALENESS    │                             │
                    │     CHECK       │                             │
                    │                  │                             │
                    │  next_review_date│                             │
                    │  < today?        │                             │
                    │                  │                             │
                    │  YES → cap conf  │                             │
                    │  at threshold-1  │                             │
                    │  (forces State 2)│                             │
                    └────────┬─────────┘                             │
                             │                                      │
                             ▼                                      │
                    ┌─────────────────┐                             │
                    │  5. GATE         │                             │
                    │     DECISION    │                             │
                    │                  │                             │
                    │  conf >= 0.85    │                             │
                    │  AND status =    │                             │
                    │  "certified"?    │                             │
                    └───┬─────────┬────┘                             │
                        │         │                                  │
                   YES  │         │  NO                              │
                        ▼         ▼                                  ▼
           ┌────────────────┐   ┌────────────────────────────────────────┐
           │  STATE 1       │   │  STATE 2                                │
           │  Certified     │   │  Analytical Lane                        │
           │  Lane          │   │                                         │
           └────────────────┘   └─────────────────────────────────────────┘
```

### Step Details

#### Step 1 — Retrieve

| Aspect | Detail |
| --- | --- |
| Input | User prompt (raw text) |
| Operation | Embed prompt via `databricks-bge-large-en`, query `certified_qa_index` with `top_k=3` |
| Output | List of `Candidate` objects: `{corpus_id, question, score, status, next_review_date, parameterized_sql, answer_template, parameters}` |
| Filters | Only return candidates where `status IN ('certified', 'draft')` |

#### Step 2 — Short-Circuit Check

| Condition | Action |
| --- | --- |
| No candidates returned (empty index) | Route to Analytical Lane, `confidence = 0.0` |
| Vector Search API call failed (timeout/error) | Route to Analytical Lane, `confidence = 0.0`, log error |
| At least one candidate | Continue to Step 3 |

#### Step 3 — Rerank / Calibrate

| Aspect | Detail |
| --- | --- |
| Candidate selection | Pick the candidate with the highest VS similarity score |
| LLM Judge prompt | `"Does the user question '{prompt}' have the same intent as the certified question '{candidate.question}'? Score 0 to 100 where 100 = identical intent."` |
| Judge model | Foundation model endpoint (e.g., `databricks-meta-llama-3-3-70b-instruct`) |
| Normalization | `raw_score / 100.0` → value in `[0.0, 1.0]` |
| Linear shrink | `calibrated = normalized * shrink_factor` (default `shrink_factor = 0.95`) to prevent over-confidence |
| Rationale | Raw VS similarity is not intent-aware; the LLM judge adds semantic understanding while the shrink prevents borderline questions from falsely clearing the gate |

#### Step 4 — Staleness Check

| Aspect | Detail |
| --- | --- |
| Check | `candidate.next_review_date < current_date()` |
| If stale | `confidence = min(confidence, threshold - 0.01)` — forces the question into the Analytical Lane regardless of match quality |
| If fresh | No modification to confidence |
| Rationale | Stale entries may reference outdated SQL, schemas, or business logic; they must not serve certified answers until an SME re-certifies them |

#### Step 5 — Gate Decision

| Condition | Lane | Badge |
| --- | --- | --- |
| `confidence >= threshold` AND `candidate.status == 'certified'` | **Certified Lane** (State 1) | `HUMAN APPROVED` |
| `confidence < threshold` OR `candidate.status != 'certified'` | **Analytical Lane** (State 2) | `NOT YET APPROVED` |

Default threshold: **0.85** (configurable via `CONFIDENCE_THRESHOLD` env var)

### Certified Lane (State 1) — Execution Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    CERTIFIED LANE                              │
│                                                              │
│  1. Extract Parameters                                        │
│     LLM extracts values from prompt for each parameter       │
│     in candidate.parameters[] using an allow-list approach   │
│                                                              │
│  2. Bind SQL                                                  │
│     Insert extracted values into candidate.parameterized_sql │
│     using parameterized query execution (no string concat)   │
│                                                              │
│  3. Execute SQL                                               │
│     Run bound SQL against SQL Warehouse                      │
│     (SQL_WAREHOUSE_ID from config)                           │
│                                                              │
│  4. Format Answer                                             │
│     Render candidate.answer_template with query results      │
│     (Jinja-style template substitution)                      │
│                                                              │
│  5. Return RouterResult                                       │
│     badge: "HUMAN APPROVED"                                   │
│     confidence: <calibrated score>                            │
│     lane: "certified"                                         │
│     provenance: {corpus_id, sql, params, latency, timestamp} │
└──────────────────────────────────────────────────────────────┘
```

| Step | Detail |
| --- | --- |
| Extract parameters | LLM prompt: `"Extract values for parameters {params} from: '{user_prompt}'. Return JSON."` |
| Allow-list validation | Each extracted value is checked against expected types/patterns before binding |
| SQL execution | Uses `statement_execution` API with parameterized queries (prevents injection) |
| Template rendering | Jinja2 `answer_template.render(**result_dict)` |
| Provenance | Full audit trail: corpus_id, original certified question, executed SQL, parameters, execution time |

### Analytical Lane (State 2) — Execution Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    ANALYTICAL LANE                             │
│                                                              │
│  1. Forward to Genie Space                                    │
│     POST /api/2.0/genie/spaces/{GENIE_SPACE_ID}/             │
│          conversations → start_conversation                   │
│     Body: {"content": "<user_prompt>"}                        │
│                                                              │
│  2. Poll for Completion                                       │
│     GET conversation messages until                           │
│     status = COMPLETED or timeout                            │
│                                                              │
│  3. Collect Results                                           │
│     Extract: generated SQL, answer text, attachments         │
│                                                              │
│  4. Return RouterResult                                       │
│     badge: "NOT YET APPROVED"                                 │
│     confidence: <calibrated score> (below threshold)          │
│     lane: "analytical"                                        │
│     provenance: {genie_space_id, genie_sql, latency}         │
│     suggestion: "Request SME Review"                          │
└──────────────────────────────────────────────────────────────┘
```

| Step | Detail |
| --- | --- |
| Genie invocation | Conversation API handles SQL generation, execution, and natural language response |
| Timeout handling | If Genie doesn't respond within `GENIE_TIMEOUT_SEC` (default 30s), return a graceful error message |
| SME review hook | Response includes a `"Request SME Review"` action that logs the prompt + Genie answer to `sme_review_queue` for the certification flywheel |

### Configuration Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `CONFIDENCE_THRESHOLD` | `0.85` | Gate threshold for certified lane routing |
| `VS_TOP_K` | `3` | Number of candidates to retrieve from Vector Search |
| `SHRINK_FACTOR` | `0.95` | Linear shrink applied after normalization |
| `JUDGE_MODEL` | `databricks-meta-llama-3-3-70b-instruct` | LLM used for intent reranking |
| `GENIE_SPACE_ID` | — | Genie Space for analytical lane |
| `GENIE_TIMEOUT_SEC` | `30` | Max wait for Genie response |
| `SQL_WAREHOUSE_ID` | — | Warehouse for certified SQL execution |

### MLflow Tracing Integration

Every supervisor invocation produces a trace with the following spans:

```
router.predict (root span)
├── router.retrieve          → VS query latency, num_candidates, top_score
├── router.rerank            → judge_model, raw_score, calibrated_score
├── router.staleness_check   → is_stale, original_confidence, capped_confidence
├── router.gate_decision     → threshold, final_confidence, lane_chosen
│
├── [if certified] router.certified_lane
│   ├── router.extract_params    → parameters extracted, validation results
│   ├── router.execute_sql       → sql, warehouse_id, execution_ms
│   └── router.format_answer     → template_used, answer_length
│
└── [if analytical] router.analytical_lane
    ├── router.genie_call        → space_id, conversation_id, poll_count
    └── router.genie_result      → sql_generated, answer_length
```

---

### UI → Model Serving Integration (End-to-End Request Flow)

The Flask UI triggers the router agent via the **Model Serving endpoint**. The notebook
(`notebooks/router_agent`) is a development/registration artifact — it is NOT called at runtime.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           RUNTIME REQUEST FLOW                                   │
│                                                                                 │
│  ┌────────────┐     ┌────────────────────┐     ┌──────────────────────────────┐ │
│  │  User      │     │  Flask App         │     │  Model Serving Endpoint      │ │
│  │  Browser   │     │  (DB App)          │     │  bannerwise-quality-router   │ │
│  │            │     │                    │     │                              │ │
│  │  Ask page  │────▶│  POST /api/quality │────▶│  BannerwiseQualityRouter     │ │
│  │  (ask.html)│     │       /assess      │     │  .predict()                  │ │
│  │            │◀────│                    │◀────│                              │ │
│  │  Renders   │     │  router_service.py │     │  → Vector Search (always)    │ │
│  │  response  │     │  calls endpoint    │     │  → Gate decision             │ │
│  │            │     │  via HTTP/SDK      │     │  → Certified or Genie lane   │ │
│  └────────────┘     └────────────────────┘     └──────────────────────────────┘ │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

#### Lifecycle: From Development to Production

| Phase | Artifact | Purpose |
| --- | --- | --- |
| **1. Development** | `notebooks/router_agent` | Define, test, and iterate on `BannerwiseQualityRouter` |
| **2. Registration** | MLflow → Unity Catalog | `mlflow.pyfunc.log_model()` registers the agent to `aw_serverless_stable_catalog.bannerhealth.bannerwise_quality_router` |
| **3. Serving** | Model Serving endpoint | Defined in `resources/bannerwise_quality_agent.ai.yml` → serves the registered UC model |
| **4. UI Integration** | `apps/services/router_service.py` | Flask service calls the Model Serving endpoint via `WorkspaceClient().serving_endpoints.query()` |
| **5. Runtime** | User → Flask → Endpoint | Every user prompt flows through: Ask page → Flask route → Model Serving → Router → Response |

#### Flask Service Layer (router_service.py)

```python
# apps/services/router_service.py (live mode)
from databricks.sdk import WorkspaceClient

SERVING_ENDPOINT = os.getenv("SERVING_ENDPOINT", "bannerwise-quality-router")

def assess_prompt(prompt: str) -> dict:
    """Call the Model Serving endpoint to route the user's prompt."""
    w = WorkspaceClient()
    response = w.serving_endpoints.query(
        name=SERVING_ENDPOINT,
        dataframe_records=[{"prompt": prompt}]
    )
    return response.predictions[0]  # RouterResult dict
```

#### Mode Toggle (Mock vs Live)

| Mode | Triggered via | Service used | When |
| --- | --- | --- | --- |
| `mock` | `API_MODE=mock` in `config.py` | `mock_router_service.py` (static responses) | Local dev, UI prototyping |
| `live` | `API_MODE=live` in `app.yaml` | `router_service.py` (calls Model Serving) | Deployed app (dev/prod) |

The `quality_routes.py` route handler checks `config.API_MODE` and dispatches to the appropriate service:

```python
# apps/routes/quality_routes.py
if current_app.config["API_MODE"] == "live":
    from services.router_service import assess_prompt
else:
    from services.mock_router_service import assess_prompt
```

## Component Design

### 1. Router Agent (Python — MLflow Pyfunc)

```
class BannerwiseQualityRouter(mlflow.pyfunc.PythonModel):
    """
    Deterministic router with confidence gate.
    Registered in Unity Catalog, served via Model Serving.
    """
    - predict() → RouterResult
    - _retrieve(prompt) → List[Candidate]
    - _rerank(prompt, candidate) → float
    - _calibrate(raw_score, candidate) → float
    - _certified_lane(prompt, candidate) → RouterResult
    - _analytical_lane(prompt) → RouterResult
```

**RouterResult dataclass:**
- `answer: str` — formatted response
- `badge: str` — "HUMAN APPROVED" | "NOT YET APPROVED"
- `confidence: float` — calibrated score
- `lane: str` — "certified" | "analytical"
- `provenance: dict` — corpus_id, sql_executed, sources, latency, timestamp

### 2. Flask Web Application

| Layer | Components |
| --- | --- |
| Routes | `quality_routes.py` (prompt → endpoint), `health_routes.py`, `admin_routes.py`, `corpus_routes.py`, `history_routes.py` |
| Services | `router_service.py` (calls serving endpoint), `corpus_service.py` (reads Delta table), `history_service.py` (stores past queries) |
| Middleware | `auth_middleware.py` (workspace identity validation) |
| Models | `router_result.py`, `corpus_entry.py`, `query_history.py` |
| Templates | `layout.html`, `ask.html`, `history.html`, `corpus.html`, `admin.html` |

**App factory pattern** with blueprint registration, config from environment.

### 3. Model Serving Endpoint

- Registered model: `aw_serverless_stable_catalog.bannerhealth.bannerwise_quality_router`
- Endpoint: real-time inference, autoscaling
- Input: `{"prompt": "..."}`
- Output: `RouterResult` JSON
- **Deployment**: Deployed via `router_agent_job` → `deploy_serving_endpoint` task
- The supervisor agent is registered to UC via MLflow, then served via Model Serving

### 4. Vector Search

- Endpoint: `bannerwise-vs-endpoint` (STANDARD)
- Index: `aw_serverless_stable_catalog.bannerhealth.certified_qa_index` (Delta Sync)
- Source table: `aw_serverless_stable_catalog.bannerhealth.certified_qa_corpus`
- Embedding model: `databricks-bge-large-en`
- Columns synced: `id`, `question`, `parameterized_sql`, `answer_template`, `parameters`, `status`, `certified_by`, `certified_date`, `next_review_date`
- Pipeline type: `TRIGGERED`
- **Deployment**: VS endpoint created via bundle (`resources/bannerwise_quality_agent.ai.yml`); VS index created by `vector_index_job` (requires corpus table to exist first)

---

## Data Model

### Certified QA Corpus Table

```sql
CREATE TABLE catalog.schema.certified_qa_corpus (
    id              STRING      NOT NULL,
    question        STRING      NOT NULL,
    question_embedding ARRAY<FLOAT>,
    parameterized_sql STRING    NOT NULL,
    answer_template STRING      NOT NULL,
    parameters      ARRAY<STRING>,
    status          STRING      DEFAULT 'draft',  -- certified | draft | expired
    certified_by    STRING,
    certified_date  TIMESTAMP,
    next_review_date DATE       NOT NULL,
    created_at      TIMESTAMP   DEFAULT current_timestamp(),
    updated_at      TIMESTAMP   DEFAULT current_timestamp()
);
```

### Query History Table

```sql
CREATE TABLE catalog.schema.query_history (
    id              STRING      NOT NULL,
    user_email      STRING      NOT NULL,
    prompt          STRING      NOT NULL,
    lane            STRING      NOT NULL,  -- certified | analytical
    confidence      FLOAT,
    badge           STRING,
    corpus_id       STRING,     -- NULL for analytical
    sql_executed    STRING,
    answer          STRING,
    latency_ms      INT,
    timestamp       TIMESTAMP   DEFAULT current_timestamp()
);
```

---

## Deployment Architecture

```
Declarative Automation Bundles (DABs)
bannerwise-app/                        (Bundle Root)
├── databricks.yml                      include: resources/*.yml
│   ├── Target: dev (development mode, default)
│   └── Target: prod (production mode)
│
├── resources/
│   ├── bannerwise_quality_agent.app.yml
│   │   └── App resource (Flask + Gunicorn on DB Apps)
│   │
│   ├── bannerwise_quality_agent.ai.yml
│   │   ├── vector_search_endpoints:
│   │   │   └── bannerwise_vs_endpoint (STANDARD)
│   │   ├── vector_search_indexes:
│   │   │   └── certified_qa_index (DELTA_SYNC)
│   │   │       ├── source: certified_qa_corpus
│   │   │       ├── embedding: question → databricks-bge-large-en
│   │   │       └── pipeline_type: TRIGGERED
│   │   └── model_serving_endpoints:
│   │       └── bannerwise_quality_router
│   │           ├── model: aw_serverless_stable_catalog.bannerhealth.bannerwise_quality_router
│   │           ├── workload: CPU (autoscaling)
│   │           └── called by: apps/services/router_service.py
│   │
│   └── bannerwise_quality_agent_jobs.job.yml
│       └── setup_job (create_tables → generate_synthetic_data)
│
├── notebooks/
│   ├── router_agent               (Supervisor agent: define, test, register to UC)
│   ├── create_tables              (DDL for data model)
│   └── generate_synthetic_data    (dbldatagen test data)
│
└── apps/                           (Flask source_code_path)
    ├── app.py, config.py, routes/, services/, templates/, static/
    └── app.yaml (gunicorn, env vars)
```

### Resource Deployment Strategy

The **router agent** and its supporting AI infrastructure are deployed as a unit through
`resources/bannerwise_quality_agent.ai.yml`. This ensures:

| Concern | How It's Handled |
| --- | --- |
| **Atomic deployment** | VS endpoint, index, and (future) model serving endpoint are declared together |
| **Dependency ordering** | Index references the endpoint by name; DABs handles creation order |
| **Environment parity** | Same resource file for dev/prod targets; variables swap catalog/schema |
| **Drift detection** | `bundle validate` catches config mismatches before deploy |
| **Reproducibility** | Entire AI stack is version-controlled alongside app code |

### Environment Configuration

| Variable | Dev | Prod |
| --- | --- | --- |
| `CONFIDENCE_THRESHOLD` | 0.85 | 0.85 |
| `VS_ENDPOINT` | `bannerwise-vs-endpoint` | `bannerwise-vs-endpoint` |
| `VS_INDEX` | `catalog.schema.certified_qa_index` | `catalog.schema.certified_qa_index` |
| `SERVING_ENDPOINT` | `bannerwise-quality-router-dev` | `bannerwise-quality-router` |
| `GENIE_SPACE_ID` | `<dev-space-id>` | `<prod-space-id>` |
| `SQL_WAREHOUSE_ID` | `<warehouse-id>` | `<warehouse-id>` |

---

## Certification Flywheel

```
User asks question (State 2)
       │
       ▼
Clicks "Request SME Review"
       │
       ▼
Logged to review queue (Delta table)
       │
       ▼
SME reviews in Admin page
       │
       ├── Approves → Adds to corpus → VS index auto-syncs
       │                                     │
       │                    Next identical question → State 1
       │
       └── Rejects → Logged and discarded
```

This creates a **self-improving loop**: every approved review grows the corpus, increasing the probability that future questions hit the Certified Lane.

---

## MLflow Tracing Schema

Every request produces a trace with spans:

| Span | Attributes |
| --- | --- |
| `router.predict` | prompt, final_lane, confidence, latency_ms |
| `router.retrieve` | num_candidates, top_score, vs_latency_ms |
| `router.rerank` | raw_score, calibrated_score, judge_model |
| `router.certified_lane` | corpus_id, sql, parameters_extracted |
| `router.analytical_lane` | genie_space_id, genie_sql, genie_answer_length |

---

## Security & Access Control

| Concern | Approach |
| --- | --- |
| Authentication | Databricks workspace identity (OAuth) |
| Admin access | `ADMIN_USERS` env var (phase 1), Delta table ACL (phase 2) |
| SQL injection | Parameterized SQL only; parameters validated via allow-list |
| Corpus integrity | Only certified entries with valid `next_review_date` are served |
| Secrets | Databricks secret scope (`bannerwise-quality-agent/*`) |
