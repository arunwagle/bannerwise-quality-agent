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

- Registered model: `catalog.schema.bannerwise_quality_router`
- Endpoint: real-time inference, autoscaling
- Input: `{"prompt": "..."}`
- Output: `RouterResult` JSON

### 4. Vector Search

- Endpoint: `bannerwise-vs-endpoint`
- Index: `certified_qa_index` (Delta Sync from corpus table)
- Embedding model: Databricks Foundation Model (e.g., `databricks-bge-large-en`)
- Columns synced: `question`, `question_embedding`, `id`, `status`, `next_review_date`

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
├── databricks.yml
│   ├── App resource (Flask + Gunicorn)
│   ├── Target: dev (development mode)
│   └── Target: prod (production mode)
│
├── Model Serving Endpoint (registered separately via MLflow)
│
└── Supporting resources:
    ├── Delta tables (corpus, history)
    ├── Vector Search endpoint + index
    └── Genie Space (analytical lane)
```

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
