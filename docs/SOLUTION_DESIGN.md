# Bannerwise Quality Agent — Technical Solution Design

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                    BannerWise Databricks App                        │
│                  (Flask + Gunicorn on DB Apps)                      │
└────────────────────────────────────┬───────────────────────────────┘
                                     │ User Prompt
                                     ▼
┌────────────────────────────────────────────────────────────────────┐
│              CONFIDENCE GATE (Model Serving Endpoint)               │
│                                                                    │
│   embed → Vector Search retrieve (top-k) → LLM Judge →            │
│   confidence score (0.0 or 1.0 based on judge verdict)             │
└────────────────────────────────────┬───────────────────────────────┘
                                     │
                            confidence >= 0.5
                            AND status = certified?
                                     │
                      ┌──── YES ─────┴───── NO ────┐
                      ▼                            ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│ CERTIFIED LANE            │    │ ANALYTICAL LANE            │
│ (green badge)             │    │ (amber badge)              │
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

## 2. Router Agent — Detailed Design

The Router Agent is an MLflow PyFunc model served via Databricks Model Serving. It implements a 3-step pipeline: **Retrieve → Judge → Gate**.

> **Design Philosophy**: The router uses a deterministic pipeline (not agentic tool selection) to ensure predictable, auditable routing decisions. Every question always goes through the same 3 steps in the same order.

---

### Step 1 — Vector Search Retrieval

**Current Behavior:**

The user's prompt is embedded using `databricks-bge-large-en` and compared against the `certified_qa_index` (cosine similarity). The top `k=3` candidates are returned with their similarity scores.

| Aspect | Detail |
| --- | --- |
| Embedding Model | `databricks-bge-large-en` |
| Index | `aw_serverless_stable_catalog.bannerhealth.certified_qa_index` |
| Sync Mode | Delta Sync (TRIGGERED — manually synced on certify action) |
| Top-K | 3 candidates |
| Similarity | Cosine |
| Fields Returned | `corpus_id`, `question`, `score`, `status`, `parameterized_sql`, `answer_template`, `parameters` |
| CDF Requirement | Source table must have Change Data Feed enabled for Delta Sync |

**How it works:**
- Vector Search returns candidates ranked by cosine similarity (0.0–1.0)
- A score of 0.68+ typically indicates a reasonable semantic match
- However, **VS score alone is insufficient** for routing — two questions can have high similarity but different intent (e.g., "ROI for summer campaign" vs. "highest ROI campaign")
- That's why Step 2 (LLM Judge) is critical

**Possible Enhancements:**
- **Hybrid search**: Combine vector similarity with keyword/BM25 matching for better recall on short queries
- **Pre-filtering by status**: Only retrieve `status='certified'` entries (skip expired/draft)
- **Dynamic top-k**: Increase k for ambiguous queries, decrease for high-confidence single matches
- **Embedding fine-tuning**: Train a domain-specific embedding model on Banner Health's Q&A pairs
- **Multi-index retrieval**: Separate indexes for different question categories (spend, performance, attribution)

---

### Step 2 — LLM Judge

**Current Behavior:**

The LLM Judge receives the user's question and the top corpus candidate, then evaluates whether they have the **same semantic intent**. It outputs a binary **YES/NO** verdict.

| Aspect | Detail |
| --- | --- |
| Model | `databricks-meta-llama-3-3-70b-instruct` |
| Input | User prompt + best corpus candidate question |
| Output | Binary: `YES` (same intent) or `NO` (different intent) |
| Prompt Design | "Does the user's question have the same intent as this certified question? Consider that parameters (dates, campaign names) may differ but the underlying analytical question is the same." |

**How it works:**
- The judge is asked a simple equivalence question
- `YES` means: the user is asking the same thing as the certified question, possibly with different parameters
- `NO` means: the user is asking something fundamentally different
- This maps to confidence: YES → 1.0, NO → 0.0

**Examples:**

| User Question | Corpus Match | Judge | Why |
| --- | --- | --- | --- |
| "What is the total ad spend for Q1 2025?" | "What is the total ad spend for {period}?" | YES | Same intent, different parameter |
| "Which campaign had the highest ROI?" | "What was the ROI for the {campaign} campaign?" | NO | User wants ranking across ALL campaigns; corpus asks about ONE specific campaign |
| "Compare CPM across all regions" | "Which regions have the highest CPM?" | YES | Same analytical intent, different phrasing |

**Possible Enhancements:**
- **Graduated confidence scoring**: Instead of binary YES/NO, have the judge output a confidence score (0–100). This creates a meaningful range:
  - 85–100: High confidence → Certified Lane
  - 50–84: Medium confidence → Certified Lane with "verify" flag
  - 25–49: Low confidence → Analytical Lane with "similar certified answer available" note
  - 0–24: No match → Analytical Lane
- **Multi-candidate evaluation**: Judge all top-k candidates (not just the best) and pick the highest-scoring one
- **Chain-of-thought reasoning**: Ask the judge to explain reasoning before concluding
- **Few-shot examples**: Include labeled examples in the judge prompt for better calibration
- **Judge ensemble**: Use 2 different LLMs as judges and require agreement
- **Parameter-aware judging**: Explicitly tell the judge which parameters are expected

---

### Step 3 — Confidence Gate

**Current Behavior:**

The gate is a simple threshold check. Since the judge outputs binary (0.0 or 1.0), the threshold of 0.5 is merely a separator — any value between 0.01 and 0.99 would produce identical behavior.

| Aspect | Detail |
| --- | --- |
| Threshold | `0.5` (configurable via `CONFIDENCE_THRESHOLD`) |
| Judge YES → confidence 1.0 | Passes gate → **Certified Lane** |
| Judge NO → confidence 0.0 | Fails gate → **Analytical Lane** |
| Effect of threshold | With binary judge, threshold is just a separator. No query ever scores between 0 and 1. |

**Why this works for a demo:**
The binary approach is simple, predictable, and easy to explain. The quality control lives entirely in the judge prompt quality, not in threshold tuning.

**Possible Enhancements:**
- **Graduated thresholds** (requires graduated judge above):
  - `threshold_certified = 0.85` — high bar for certified answers
  - `threshold_suggest = 0.50` — medium bar for "similar certified answer available"
  - Below 0.50 — pure analytical lane
- **Dynamic thresholds**: Adjust based on corpus coverage per domain
- **Shrink factor**: A multiplier on the judge score to account for over-confidence (`final_score = raw_score * shrink_factor`). Currently 1.0 (no shrink).
- **Multi-gate routing**: Add a third "human-in-the-loop" lane for borderline cases (50–85%)

---

## 3. Certified Lane — Execution Flow

When the gate says YES, the certified lane executes the pre-approved SQL with extracted parameters.

```
┌──────────────────────────────────────────────────────────────┐
│                    CERTIFIED LANE                              │
│                                                              │
│  1. Lookup corpus entry by corpus_id                          │
│     → parameterized_sql, answer_template, parameters         │
│                                                              │
│  2. Extract parameters from user prompt via LLM               │
│     Prompt: "Extract {period} from: 'total ad spend Q1 2025'"│
│     → {"period": "Q1 2025"}                                  │
│                                                              │
│  3. Bind parameters into SQL template                         │
│     "SELECT SUM(spend) FROM ad_metrics WHERE period = :period"│
│     → "SELECT SUM(spend) ... WHERE period = 'Q1 2025'"       │
│                                                              │
│  4. Execute SQL via SQL Warehouse (statement_execution API)   │
│     → {"total_spend": 254500.75}                             │
│                                                              │
│  5. Format answer using LLM + answer_template                 │
│     Template: "Total ad spend for {period} was ${total_spend}"│
│     → "The total ad spend for Q1 2025 was $254,500.75."      │
│                                                              │
│  6. Return with badge: "Certified" + full provenance         │
└──────────────────────────────────────────────────────────────┘
```

**LLM Endpoint**: `databricks-meta-llama-3-3-70b-instruct` (for parameter extraction and answer formatting)

---

## 4. Analytical Lane — Execution Flow

When the gate says NO, the analytical lane forwards to the Genie Space for dynamic SQL generation.

```
┌──────────────────────────────────────────────────────────────┐
│                    ANALYTICAL LANE (Genie Space)               │
│                                                              │
│  1. POST /api/2.0/genie/spaces/{id}/start-conversation       │
│     Body: {"content": "<user_prompt>"}                        │
│                                                              │
│  2. Poll GET .../messages/{id} until COMPLETED or timeout     │
│     (polling interval: 2s, max wait: 60s)                    │
│                                                              │
│  3. Extract from response attachments:                        │
│     - Generated SQL from attachment.query.query               │
│     - Answer text from attachment.text.content                │
│                                                              │
│  4. Return with badge: "Not Certified"                        │
│     Provenance: {source: "genie_space", genie_status,        │
│                  sql_executed, genie_error}                   │
│                                                              │
│  5. User can click "Add to SME Review" → enters flywheel     │
└──────────────────────────────────────────────────────────────┘
```

**Genie Space Configuration:**
- 9 analytics tables registered
- 15 sample questions + 15 example SQL pairs
- Instructions: "Always answer directly, never ask clarifying questions"
- Deployed as a DABs resource (`engine: direct` required for Genie resources)

---

## 5. Certification Flywheel

The certification flywheel is the mechanism by which the system self-improves over time. Each uncertified answer is an opportunity to expand the certified corpus.

```
User asks question → Analytical Lane (Not Certified)
       │
       ▼
Clicks "Add to SME Review"
       │
       ▼
Draft saved to certified_qa_corpus_draft table
(id: DRAFT-{8hex}, question, sql, answer, submitted_by, original_prompt)
       │
       ▼
SME opens Review page → sees question + SQL + answer
       │
       ├── "Run Modified Query" → test/edit SQL in textarea, preview results
       │
       ├── "Certify" → moves to certified_qa_corpus (new QA-XXXX id)
       │                 → Triggers VS index sync via SDK (sync_index API)
       │                 → Next similar question routes to Certified Lane ✅
       │
       └── "Reject" → removed from draft table
```

**Key design decisions:**
- CDF must remain enabled on `certified_qa_corpus` for Delta Sync to work
- Test data uses TRUNCATE + append (not `mode("overwrite")`) to preserve CDF
- Certified entries get a 180-day `next_review_date` (staleness gate)
- The Review page allows SQL modification before certification (SME can fix the query)
- **SQL validation gate**: Before certification, `EXPLAIN` is run against the SQL to catch syntax errors (e.g., malformed regex, unquoted literals). Parameter placeholders (`:param`) are substituted with dummy values for validation. If validation fails, certify returns HTTP 422 with the error — the entry remains in draft.

---

## 6. Jobs Design — Initial Setup & Deployment Pipeline

### Deployment Order

The jobs must be run in sequence for a fresh deployment:

```
1. bundle deploy --target dev
       │
       ▼
2. setup_job (creates schema + tables + synthetic data)
       │
       ▼
3. setup_access_job (grants permissions to app SP)
       │
       ▼
4. vector_index_job (builds VS index from certified corpus)
       │
       ▼
5. router_agent_job (trains, evaluates, registers, deploys model)
       │
       ▼
6. App deploy (manual — Databricks Apps deployment)
```

---

### Job 1: `bannerwise-quality-agent-setup`

**Purpose:** Initialize the data layer — create schema, tables, and populate with synthetic data.

| Task | Notebook | Depends On | Actions |
| --- | --- | --- | --- |
| `create_schema_and_tables` | `notebooks/data/create_tables` | — | Creates all system + analytics tables (with CDF on corpus) |
| `create_analytics_tables` | `notebooks/data/create_synthetic_data` | `create_schema_and_tables` | Generates 9 analytics tables + seeds corpus with 20 entries |

**Parameters passed:** `catalog_name`, `schema_name`

**Tables created:**
- System: `certified_qa_corpus` (CDF enabled), `certified_qa_corpus_draft`, `query_history`, `sme_review_queue`, `router_eval_dataset`, `router_eval_results`
- Analytics: `ad_metrics`, `campaign_metrics`, `banner_performance`, `regional_metrics`, `network_metrics`, `channel_metrics`, `session_metrics`, `creative_performance`, `attribution_metrics`

---

### Job 2: `bannerwise-quality-agent-access`

**Purpose:** Grant the application service principal all required permissions. All 4 tasks run in **parallel** (no dependencies between them).

| Task | Notebook | Permissions Granted |
| --- | --- | --- |
| `configure_uc_access` | `notebooks/access/setup_uc_access` | USE CATALOG, USE SCHEMA, SELECT, MODIFY + CAN_USE on SQL Warehouse |
| `configure_vs_access` | `notebooks/access/setup_vs_access` | CAN_USE on VS endpoint `bannerwise-vs-endpoint` |
| `configure_endpoint_access` | `notebooks/access/setup_endpoint_access` | CAN_QUERY on serving endpoint + LLM endpoint |
| `configure_genie_access` | `notebooks/access/setup_genie_access` | CAN_RUN on Genie Space (via `/api/2.0/permissions/genie/{id}`) |

**Parameters passed:** `app_sp_id` (from `${resources.apps.bannerwise_quality_agent.service_principal_id}`), resource IDs

**Important note on Genie permissions:** The correct API path is `/api/2.0/permissions/genie/{space_id}` — NOT `/permissions/dashboards/` or `/permissions/genie-spaces/`. This was discovered through trial and error.

---

### Job 3: `bannerwise-quality-agent-vector-index`

**Purpose:** Create and populate the Vector Search Delta Sync index.

| Task | Notebook | Actions |
| --- | --- | --- |
| `setup_certified_corpus` | `notebooks/vs/create_vector_search_index` | 1. Verify VS endpoint exists  2. Create Delta Sync index  3. Wait for ONLINE status  4. Verify with test query |

**Index configuration:**
- Source: `certified_qa_corpus` (requires CDF enabled)
- Column: `question` → embedded via `databricks-bge-large-en`
- Sync mode: TRIGGERED (manually triggered on each certify action via `sync_index` API)
- Columns synced: `id`, `question`, `parameterized_sql`, `answer_template`, `parameters`, `status`, `certified_by`, `certified_date`, `next_review_date`

**Prerequisites:**
- `certified_qa_corpus` must exist and have data
- CDF must be enabled on the table
- VS endpoint `bannerwise-vs-endpoint` must be provisioned (by DABs deploy)

---

### Job 4: `bannerwise-quality-agent-router`

**Purpose:** Train the router agent, evaluate it, register as MLflow model, deploy to Model Serving, and configure AI Gateway.

| Task | Notebook | Depends On | Actions |
| --- | --- | --- | --- |
| `run_router_agent` | `notebooks/agent/router_agent` | — | Define PyFunc model, log to MLflow, test locally |
| `run_eval` | `notebooks/eval/run_router_eval_v2` | `run_router_agent` | Run eval dataset against model, compute metrics |
| `register_model` | `notebooks/agent/register_router_model` | `run_eval` | Register to UC, set alias "champion" |
| `deploy_serving_endpoint` | `notebooks/agent/deploy_serving_endpoint` | `register_model` | Create/update endpoint, wait for READY |
| `configure_ai_gateway` | `notebooks/agent/configure_ai_gateway` | `deploy_serving_endpoint` | Enable gateway, rate limits, inference logging |

**Parameters:** `catalog_name`, `schema_name`, `model_name`, `serving_endpoint_name`, `judge_model`, `confidence_threshold`, `shrink_factor`, VS params, Genie params

---

### Job 5: `bannerwise-quality-agent-eval`

**Purpose:** Standalone evaluation pipeline (can be run independently to re-evaluate after corpus changes).

| Task | Notebook | Depends On | Actions |
| --- | --- | --- | --- |
| `generate_eval_dataset` | `notebooks/eval/generate_eval_dataset` | — | Generate positive + negative + edge case pairs |
| `run_router_eval` | `notebooks/eval/run_router_eval_v2` | `generate_eval_dataset` | Call serving endpoint for each pair, record results |
| `check_eval_thresholds` | `notebooks/eval/check_eval_thresholds` | `run_router_eval` | Quality gates: precision≥0.90, recall≥0.85, F1≥0.87, p95 latency<5s |

**Quality gates (if thresholds fail → job fails → no promotion):**
- Precision ≥ 0.90 (certified predictions are correct)
- Recall ≥ 0.85 (certified questions are found)
- F1 ≥ 0.87
- p95 latency < 5000ms

---

### Job 6: `bannerwise-quality-agent-cleanup`

**Purpose:** Tear down all resources (for full reset or decommissioning).

| Task | Depends On | Actions |
| --- | --- | --- |
| `cleanup_vector_index` | — | Delete VS index |
| `cleanup_serving_endpoint` | `cleanup_vector_index` | Delete Model Serving endpoint |
| `cleanup_registered_model` | `cleanup_serving_endpoint` | Delete registered model from UC |
| `cleanup_schema` | `cleanup_registered_model` | Drop all tables and schema |

Order matters: remove downstream consumers before deleting upstream resources.

---

## 7. Permissions Management

### Service Principal Model

The app runs as a Databricks App with an automatically provisioned service principal. All access is granted to this SP — no user credentials are used at runtime.

| Permission | Target | Principal | API / Method |
| --- | --- | --- | --- |
| USE CATALOG | `aw_serverless_stable_catalog` | App SP | SQL GRANT |
| USE SCHEMA | `bannerhealth` | App SP | SQL GRANT |
| SELECT | All tables in schema | App SP | SQL GRANT |
| MODIFY | Schema (for INSERT into history/draft) | App SP | SQL GRANT |
| CAN_USE | SQL Warehouse `2d8e531640ffa469` | App SP | PATCH `/permissions/warehouses/{id}` |
| CAN_USE | VS endpoint `bannerwise-vs-endpoint` | App SP | PATCH `/permissions/vector-search-endpoints/{id}` |
| CAN_QUERY | Serving endpoint `bannerwise-quality-router` | App SP | PATCH `/permissions/serving-endpoints/{id}` |
| CAN_QUERY | LLM endpoint `databricks-meta-llama-3-3-70b-instruct` | App SP | PATCH `/permissions/serving-endpoints/{id}` |
| CAN_RUN | Genie Space `01f19026d0e61c88b840ce168a9be672` | App SP | PATCH `/permissions/genie/{id}` |
| SELECT | VS Index `certified_qa_index` | Model Serving | SQL GRANT TO `system-model-serving` |
| CAN_USE | VS endpoint `bannerwise-vs-endpoint` | Model Serving | PATCH (via `users` group) |

> **Critical Note:** The Model Serving endpoint (`bannerwise-quality-router`) uses `auth_type=model-serving` — a system-managed identity **separate from the App SP**. It needs its own explicit grants on UC securables. These grants are **lost when the VS index is deleted and recreated** and must be re-applied via the `setup_access_job`.

### Permission Resolution

The `setup_access_job` resolves the app SP using:
```python
# The app's SP application_id (UUID) is passed as a job parameter
# from: ${resources.apps.bannerwise_quality_agent.service_principal_id}
sp = w.service_principals.get(app_sp_id)
# sp.application_id is the UUID used in permissions API
```

### Permission API Patterns

All permission grants follow the same pattern:
```python
w.api_client.do(
    "PATCH",
    f"/api/2.0/permissions/{resource_type}/{resource_id}",
    body={
        "access_control_list": [{
            "service_principal_name": sp_application_id,
            "permission_level": "CAN_USE"  # or CAN_QUERY, CAN_RUN
        }]
    }
)
```

---

## 8. Model Training & Deployment

### Router Agent — MLflow PyFunc

The router is a **custom MLflow PyFunc** model, not a fine-tuned LLM. It orchestrates multiple Databricks services within a single `predict()` call:

```python
class RouterAgent(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        # Initialize clients for VS, LLM, SQL warehouse
        self.vs_client = VectorSearchClient()
        self.index = self.vs_client.get_index(...)
        
    def predict(self, context, model_input):
        prompt = model_input["prompt"][0]
        
        # Step 1: Vector Search
        candidates = self.index.similarity_search(
            query_text=prompt, columns=[...], num_results=3
        )
        
        # Step 2: LLM Judge (for each candidate)
        for candidate in candidates:
            verdict = self._judge(prompt, candidate["question"])
            if verdict == "YES":
                return {
                    "lane": "certified",
                    "confidence": 1.0,
                    "corpus_id": candidate["id"],
                    "vs_score": candidate["score"],
                    ...
                }
        
        # Step 3: No match → analytical
        return {"lane": "analytical", "confidence": 0.0, ...}
```

### Model Registration Flow

```
MLflow Experiment → Log Model → Register to UC → Set Alias "champion"
     │                                                    │
     └── Metrics: precision, recall, F1, latency          │
                                                          ▼
                                              Model Serving Endpoint
                                              (GPU_SMALL, scale_to_zero)
```

### Model Versioning Strategy

| Alias | Purpose |
| --- | --- |
| `champion` | Currently deployed version serving production traffic |
| `challenger` | New version under evaluation (A/B testing) |

Promotion flow: train → eval passes thresholds → register → set alias `champion` → endpoint auto-updates.

### Serving Endpoint Configuration

| Setting | Value |
| --- | --- |
| Endpoint Name | `bannerwise-quality-router` |
| Workload Size | `GPU_SMALL` |
| Scale to Zero | `True` (cold start ~30s) |
| Model | UC registered model @ "champion" alias |
| AI Gateway | Enabled (rate limits + inference logging) |

---

## 9. Configuration Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `CONFIDENCE_THRESHOLD` | `0.5` | Gate threshold (binary judge: 1.0 passes, 0.0 fails) |
| `VS_TOP_K` | `3` | Number of candidates from Vector Search |
| `SHRINK_FACTOR` | `1.0` | Multiplier on judge score (1.0 = no adjustment) |
| `JUDGE_MODEL` | `databricks-meta-llama-3-3-70b-instruct` | LLM for semantic equivalence |
| `GENIE_SPACE_ID` | `01f19026d0e61c88b840ce168a9be672` | Genie Space for analytical lane |
| `GENIE_TIMEOUT_SEC` | `60` | Max wait for Genie response |
| `SQL_WAREHOUSE_ID` | `2d8e531640ffa469` | Warehouse for SQL execution |
| `SERVING_ENDPOINT_NAME` | `bannerwise-quality-router` | Model Serving endpoint |
| `LLM_ENDPOINT` | `databricks-meta-llama-3-3-70b-instruct` | LLM for param extraction + formatting |

---

## 10. Flask Application Services

| Service | File | Purpose |
| --- | --- | --- |
| `live_router_service.py` | Router (live) | Calls Model Serving, dispatches to certified/analytical lane |
| `demo_router_service.py` | Router (demo) | Offline demo mode — no serving endpoint needed |
| `certified_lane_service.py` | Certified lane | Lookup SQL, extract params via LLM, execute, format |
| `genie_service.py` | Analytical lane | Genie Space Conversation API (start, poll, extract) |
| `corpus_service.py` | Corpus CRUD | Submit drafts, certify, reject, list pending reviews |
| `history_service.py` | Query logging | Log queries to Delta table, read stats |

### API_MODE Selection

| Mode | env var | Service | When |
| --- | --- | --- | --- |
| Live | `API_MODE=live` | `live_router_service.py` | Deployed app |
| Demo | `API_MODE=mock` | `demo_router_service.py` | Local dev, UI testing |

---

## 11. Data Model

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

## 12. Key Resource IDs

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

## 13. Security & Access Control

| Concern | Approach |
| --- | --- |
| App Authentication | Databricks App service principal (OAuth M2M) |
| UC Permissions | GRANT USE CATALOG, USE SCHEMA, SELECT, MODIFY |
| SQL Safety | Only SELECT queries in run-query endpoint; parameterized SQL in certified lane |
| Genie Access | CAN_RUN via `/api/2.0/permissions/genie/{id}` |
| VS Access | CAN_USE on VS endpoint |
| Serving Access | CAN_QUERY on serving + LLM endpoints |
| Warehouse Access | CAN_USE on SQL warehouse |
| Rate Limiting | AI Gateway rate limits on serving endpoint |
| Audit Trail | Every query logged to `query_history` + inference table |

---

## 14. Further Reading

* [Router Test Design](ROUTER_TEST_DESIGN.md) — Evaluation methodology, test scenarios, metrics
* [Requirements](REQUIREMENTS.md) — Functional and non-functional requirements
* [UI Requirements](UI_REQUIREMENTS.md) — Frontend design specifications
* [Project Structure](PROJECT_STRUCTURE.md) — File and folder layout
