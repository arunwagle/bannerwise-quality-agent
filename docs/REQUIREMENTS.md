# Bannerwise Quality Agent — Requirements

## Objective

A **deterministic, auditable 85% confidence gate** over an SME-certified corpus, with a governed fallback and full provenance.

---

## Design Pattern Scaffolding

### 1. Certified QA Corpus (Delta Table)

- Build and maintain an SME-certified Q&A corpus stored as a Delta table
- Each entry contains: certified question, approved SQL, answer template, status (`certified` / `draft`), `next_review_date`
- Serves as the single source of truth for deterministic answers

### 2. Vector Search Index

- Create a Vector Search index (`certified_qa_index`) on the certified QA corpus
- Enables semantic similarity matching between user prompts and certified Q&A pairs
- **Embedding source column**: Uses `embedding_text` (params stripped) rather than `question` (has `{param}` placeholders)
- Rationale: embedding models treat `{period}` as a literal token, causing low similarity (0.68) for exact-intent matches. Stripping parameters improves retrieval scores to 0.82+ by focusing on analytical intent
- The `question` column is still used for LLM Judge comparison (the judge understands parameterization)

### 3. Router Agent

The router agent orchestrates the decision flow:

#### Step A — Retrieve
- Embed the user's prompt and query the Vector Search Index for top-k most similar certified Q&A pairs

#### Step B — Short-Circuit Check
- If no candidates return (index empty or VS call failed), immediately route to the **Analytical Lane** with confidence `0.0`

#### Step C — Rerank / Calibrate
- Take the top candidate and ask an LLM judge: *"Does this user question have the same intent as the certified question? Score 0–100."*
- Normalize raw score to `[0, 1]`
- Apply a placeholder linear shrink to prevent over-confidence

#### Step D — Staleness Check
- If the best candidate's `next_review_date` is in the past, forcibly cap confidence below the threshold (never serve as certified)

#### Step E — Gate Decision
- Compare calibrated confidence against the threshold (default **0.85**):
  - `>= threshold` AND status is `certified` → **Certified Lane (State 1)**
  - `< threshold` → **Analytical Lane (State 2)**

---

### 4. Certified Lane (State 1)

- Extract parameters from the user prompt via LLM
- Bind parameters into the pre-approved SQL
- Execute SQL against the warehouse
- Format the result using the stored answer template
- Return a `RouterResult` with:
  - **"HUMAN APPROVED"** badge
  - Full provenance metadata (corpus entry ID, confidence score, SQL executed, timestamp)

### 5. Analytical Lane (State 2)

- Forward the prompt to a **Genie Space** via the Conversation API
- Collect the generated answer + SQL
- Return a `RouterResult` with:
  - **"NOT YET APPROVED"** badge
  - Suggestion to request SME review

---

## MLflow Integration

- Log the router agent model to **MLflow**
- Register the model in **Unity Catalog**
- Enable **MLflow Tracing** so every request records:
  - Branch taken (Certified vs. Analytical)
  - Confidence score
  - SQL executed / sources used
  - Latency and provenance chain

## Serving Endpoint

- Create a **Model Serving endpoint** for calling the registered router agent
- Supports real-time inference with low latency
- Autoscaling based on traffic

## Frontend Application

- Build a **Flask-based Databricks App** for:
  - Testing the router agent end-to-end
  - Displaying custom badging (HUMAN APPROVED / NOT YET APPROVED)
  - Showing provenance metadata (confidence, SQL, corpus reference)
  - Integration into BannerWise platform

---

## Non-Functional Requirements

| Requirement | Target |
| --- | --- |
| Confidence threshold | 85% (configurable) |
| Deployment | Databricks App (serverless) |
| Authentication | Databricks workspace identity |
| Tracing | Full MLflow tracing on every request |
| Auditability | Complete provenance chain for certified answers |
| Staleness governance | Expired corpus entries never serve as certified |
| Fallback | Genie Space analytical lane with review suggestion |


---

## Phase 2 — Performance & Operational Improvements

### 1. Eval Job Performance Optimization

**Problem**: The eval job (`run_router_eval`) processes ~180 rows sequentially, each requiring 1 VS call + up to 3 LLM judge calls. Total: ~720 API calls at ~1-2s each = 12-20 minutes. Target: ≤ 2 minutes.

**Root Cause**: All API calls (Vector Search + LLM judge) are I/O-bound but executed serially in a `for` loop.

#### Recommended Optimizations (ordered by impact)

| # | Optimization | Expected Speedup | Complexity |
| --- | --- | --- | --- |
| 1 | **ThreadPoolExecutor (20 workers)** | 10-15x | Low |
| 2 | **Short-circuit low VS scores** (< 0.4 → skip judge) | 30-40% fewer LLM calls | Low |
| 3 | **Top-1 candidate only** in eval (not top-3) | 3x fewer judge calls | Low |
| 4 | **Spark mapInPandas** for cluster-level parallelism | Scales beyond single driver | Medium |
| 5 | **Batch judge calls** (multiple prompts per LLM request) | Reduces HTTP overhead | Medium |

#### Implementation Plan

**Optimization #1: ThreadPoolExecutor** (highest priority)
- Replace serial `for row in eval_df` loop with concurrent execution
- Use `concurrent.futures.ThreadPoolExecutor(max_workers=20)`
- LLM + VS calls are I/O-bound → threading is safe and effective
- Expected result: 180 rows in ~1-2 min instead of 15

**Optimization #2: Short-circuit low VS scores**
- If Vector Search similarity score < 0.4, skip the judge LLM call entirely
- Assign confidence = 0.0, route to analytical immediately
- Saves ~40-50% of LLM calls (adversarial, near-miss prompts score low in VS)

**Optimization #3: Top-1 candidate in eval**
- Currently fetches top-3 VS results and judges each candidate
- For eval purposes, top-1 is sufficient (VS already ranks by relevance)
- Reduces judge calls from ~540 to ~180

#### Projected Timeline

| After Optimization | Estimated Duration |
| --- | --- |
| Baseline (current) | ~15 min |
| + ThreadPool (20 workers) | ~1.5 min |
| + Short-circuit low VS | ~1 min |
| + Top-1 only | ~45s |

### 2. Champion/Challenger Model Governance

**Implemented**: New model versions are registered as `champion` only after passing the eval quality gate. The serving endpoint always deploys the `@champion` alias.

**Future enhancements**:
- Shadow traffic routing: send a % of production traffic to `@challenger` for A/B testing
- Automated rollback: if champion's live precision drops below threshold, revert to `@archived_champion`
- Model lineage tracking: tag each version with the eval run_id and metrics that promoted it

### 3. AI Gateway Observability

**Implemented**: Inference tables, usage tracking, and rate limits configured via AI Gateway.

**Future enhancements**:
- Alerting on rate limit breaches
- Dashboard for inference latency P50/P95/P99
- Cost attribution per user/team
- Guardrails: input/output safety filtering for PII detection

### 4. App Integration Hardening

**Implemented**: Live endpoint integration with WorkspaceClient SDK auth.

**Future enhancements**:
- Circuit breaker pattern: fall back to mock/cached responses if endpoint is down
- Client-side retry with exponential backoff
- Response caching for repeated identical prompts (TTL-based)
- Graceful degradation UI when endpoint is warming up (scale-to-zero)

### 5. Eval Dataset Quality

**Resolved** (stale_entry_test redesign):
- **Root cause**: Original 180 stale_entry_test prompts used generic phrasing (e.g., "bounce rate", "CTR") that matched non-stale certified entries (QA-0012, QA-0003) instead of the intended expired entries (QA-0018/0019/0020). VS returned the certified entry as a higher-scoring match → staleness check never fired → false positives.
- **Fix**: Replaced with 15 VS-verified prompts (5 per expired entry) using unique keywords:
  - QA-0018: "viewability" — term absent from all certified entries
  - QA-0019: "6-month CTR trend" — unique temporal scope (QA-0003 is "CTR by banner size")
  - QA-0020: "CPM by publisher" — unique dimension (QA-0005 is "CPM by region")
- **Validation**: All 15 prompts confirmed via VS query to return the expected expired entry as top match (scores 0.66–1.0).

**Remaining improvements** (Phase 2):
- Add adversarial categories: prompt injection via Unicode, homoglyph attacks, multi-language
- Increase dataset diversity: more colloquial rewrites, domain-specific jargon
- Add regression test suite: pin specific prompts that previously failed
