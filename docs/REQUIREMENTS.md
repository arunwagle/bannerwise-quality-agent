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
