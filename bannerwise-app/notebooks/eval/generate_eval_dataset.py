# Databricks notebook source
# MAGIC %md
# MAGIC # Generate Router Evaluation Dataset
# MAGIC
# MAGIC Reads the `certified_qa_corpus` and uses an LLM to generate a comprehensive eval dataset
# MAGIC covering paraphrases, parameter variations, near-miss negatives, adversarial prompts,
# MAGIC and unrelated questions.
# MAGIC
# MAGIC **Output**: `router_eval_dataset` table (~450 rows)
# MAGIC
# MAGIC See `docs/ROUTER_TEST_DESIGN.md` for full design rationale.

# COMMAND ----------

# MAGIC %pip install openai
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

dbutils.widgets.text("catalog_name", "aw_serverless_stable_catalog")
dbutils.widgets.text("schema_name", "bannerhealth")
dbutils.widgets.text("num_paraphrases", "7")
dbutils.widgets.text("num_near_misses", "4")
dbutils.widgets.text("num_colloquial", "3")
dbutils.widgets.text("num_param_variations", "3")
dbutils.widgets.text("judge_model", "databricks-meta-llama-3-3-70b-instruct")
dbutils.widgets.text("regenerate_dataset", "true")

CATALOG = dbutils.widgets.get("catalog_name")
SCHEMA = dbutils.widgets.get("schema_name")
NUM_PARAPHRASES = int(dbutils.widgets.get("num_paraphrases"))
NUM_NEAR_MISSES = int(dbutils.widgets.get("num_near_misses"))
NUM_COLLOQUIAL = int(dbutils.widgets.get("num_colloquial"))
NUM_PARAM_VARIATIONS = int(dbutils.widgets.get("num_param_variations"))
JUDGE_MODEL = dbutils.widgets.get("judge_model")
REGENERATE = dbutils.widgets.get("regenerate_dataset").lower() == "true"

EVAL_TABLE = f"{CATALOG}.{SCHEMA}.router_eval_dataset"
CORPUS_TABLE = f"{CATALOG}.{SCHEMA}.certified_qa_corpus"

print(f"Config:")
print(f"  Corpus: {CORPUS_TABLE}")
print(f"  Eval output: {EVAL_TABLE}")
print(f"  Paraphrases/entry: {NUM_PARAPHRASES}")
print(f"  Near-misses/entry: {NUM_NEAR_MISSES}")
print(f"  Colloquial/entry: {NUM_COLLOQUIAL}")
print(f"  Param variations/entry: {NUM_PARAM_VARIATIONS}")
print(f"  LLM: {JUDGE_MODEL}")
print(f"  Regenerate: {REGENERATE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Certified Corpus

# COMMAND ----------

# DBTITLE 1,Load Certified Corpus
from datetime import date

corpus_df = spark.table(CORPUS_TABLE)
corpus_entries = corpus_df.collect()
print(f"Loaded {len(corpus_entries)} corpus entries")

# Separate by staleness (next_review_date < today) for staleness tests
# All entries have status='certified'; stale entries are identified by past review date
certified_entries = [r for r in corpus_entries if r["status"] == "certified"]
stale_candidates = [r for r in corpus_entries if r["next_review_date"] and r["next_review_date"] < date.today()]
non_stale_entries = [r for r in certified_entries if r not in stale_candidates]

print(f"  Certified: {len(certified_entries)}")
print(f"  Stale (past next_review_date): {len(stale_candidates)} ({len(stale_candidates)/len(corpus_entries)*100:.0f}%)")
print(f"  Non-stale (active): {len(non_stale_entries)}")
assert len(stale_candidates) / len(corpus_entries) <= 0.10, f"Staleness invariant violated: {len(stale_candidates)}/{len(corpus_entries)} > 10%"

# COMMAND ----------

# MAGIC %md
# MAGIC ## LLM Helper
# MAGIC
# MAGIC Uses `dbutils` context for auth (required on serverless compute where
# MAGIC `DATABRICKS_TOKEN` env var is not set).

# COMMAND ----------

import json
from openai import OpenAI

def get_llm_client():
    """Create OpenAI client pointing to Databricks Foundation Model.
    Uses dbutils context for auth (works on serverless compute).
    """
    token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
    host = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()
    return OpenAI(api_key=token, base_url=f"{host}/serving-endpoints")

def call_llm(prompt: str, temperature: float = 0.7, max_tokens: int = 2000) -> str:
    """Call LLM and return the response content."""
    client = get_llm_client()
    try:
        response = client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"  LLM error: {e}")
        return "[]"

def parse_json_list(text: str) -> list:
    """Parse a JSON list from LLM output, handling markdown code blocks."""
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (fences)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        return []
    except json.JSONDecodeError:
        # Try to find a JSON array in the text
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                return []
        return []

# Quick validation
print("Testing LLM connectivity...")
test = call_llm("Return only a JSON array: [\"hello\"]", temperature=0)
parsed = parse_json_list(test)
assert len(parsed) > 0, f"LLM validation failed — got: {test}"
print(f"  LLM OK: {parsed}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 1: Exact Paraphrases (expected: certified)

# COMMAND ----------

# DBTITLE 1,Category 1: Exact Paraphrases (expected: certified)
from datetime import datetime

eval_rows = []

# Only generate positive cases (expected: certified) from NON-STALE entries
# Stale entries will correctly route to analytical via staleness gate
print(f"Generating {NUM_PARAPHRASES} paraphrases per non-stale certified entry...")
for entry in non_stale_entries:
    question = entry["question"]
    corpus_id = entry["id"]
    
    prompt = f"""Given this certified question: "{question}"

Generate exactly {NUM_PARAPHRASES} paraphrases that ask for the SAME core metric/analysis using different words.

Rules:
- Preserve the CORE ANALYTICAL INTENT (same metric being measured)
- Vary sentence structure, vocabulary, and phrasing
- Include formal, casual, and question-with-context variations
- If the question has parameter placeholders like {{period}} or {{campaign}}, replace them with concrete values
  (e.g., "Q1 2025", "summer campaign", "holiday", "last month", "North America")
- You MAY add specific time periods, campaign names, or regions even if the template doesn't have a placeholder
  (e.g., "What is the CTR by banner size for Q1?" is still the same intent as "What is the CTR by banner size?")
- Use concept synonyms (bounce rate = percentage who leave, viewability = percentage actually seen, CPA = cost per acquisition)
- Each paraphrase must be a complete, natural question a user would type

Do NOT change the core metric to something different (e.g., do NOT turn "CTR by banner size" into "CTR for holiday ads" — that changes the grouping dimension)

Return ONLY a JSON array of strings. Example: ["paraphrase 1", "paraphrase 2"]"""
    
    result = call_llm(prompt)
    paraphrases = parse_json_list(result)
    
    for i, p in enumerate(paraphrases[:NUM_PARAPHRASES]):
        eval_rows.append({
            "id": f"EVAL-{len(eval_rows)+1:04d}",
            "prompt": p,
            "category": "exact_paraphrase",
            "expected_lane": "certified",
            "expected_corpus_id": corpus_id,
            "difficulty": "easy" if i < 3 else "medium",
            "source_corpus_id": corpus_id,
            "generation_method": "llm_paraphrase",
            "created_at": datetime.utcnow(),
            "notes": f"Paraphrase of: {question[:80]}"
        })
    
    print(f"  {corpus_id}: {len(paraphrases)} paraphrases generated")

print(f"\nTotal paraphrase rows: {len(eval_rows)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 2: Parameter Variations (expected: certified)

# COMMAND ----------

# DBTITLE 1,Category 2: Parameter Variations (expected: certified)
print(f"Generating {NUM_PARAM_VARIATIONS} parameter variations per parameterized non-stale entry...")
param_count_before = len(eval_rows)

for entry in non_stale_entries:
    question = entry["question"]
    # Check if question has parameter placeholders
    if "{" not in question:
        continue
    
    corpus_id = entry["id"]
    params = entry["parameters"] if entry["parameters"] else "[]"
    
    prompt = f"""Given this certified question template: "{question}"
Which uses these parameters: {params}

Generate exactly {NUM_PARAM_VARIATIONS} variations of this question with DIFFERENT concrete parameter values substituted in.

For example:
- If template is "What is the total ad spend for {{period}}?", generate versions like:
  "What is the total ad spend for Q3 2024?"
  "What is the total ad spend for last month?"
  "What is the total ad spend for fiscal year 2025?"
- If it mentions {{campaign}}, substitute other plausible campaign names like "holiday_promo", "summer_blast", "q4_push"

The intent must remain the same — only the parameter values change.
Return ONLY a JSON array of strings."""
    
    result = call_llm(prompt)
    variations = parse_json_list(result)
    
    for i, v in enumerate(variations[:NUM_PARAM_VARIATIONS]):
        eval_rows.append({
            "id": f"EVAL-{len(eval_rows)+1:04d}",
            "prompt": v,
            "category": "parameter_variation",
            "expected_lane": "certified",
            "expected_corpus_id": corpus_id,
            "difficulty": "easy",
            "source_corpus_id": corpus_id,
            "generation_method": "param_variation",
            "created_at": datetime.utcnow(),
            "notes": f"Param variation of: {question[:80]}"
        })

print(f"  Parameter variation rows added: {len(eval_rows) - param_count_before}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 3: Colloquial Rewrites (expected: certified)

# COMMAND ----------

# DBTITLE 1,Category 3: Colloquial Rewrites (expected: certified)
print(f"Generating {NUM_COLLOQUIAL} colloquial rewrites per non-stale entry...")
colloquial_before = len(eval_rows)

for entry in non_stale_entries:
    question = entry["question"]
    corpus_id = entry["id"]
    
    prompt = f"""Given this formal certified question: "{question}"

Generate exactly {NUM_COLLOQUIAL} casual/colloquial rewrites — how a real user would quickly type this in a chat interface.

Rules:
- Use informal language, abbreviations, shorthand
- May drop articles, use contractions, be terse
- Must still convey the EXACT same intent
- If question has {{param}} placeholders, fill them with concrete values
- Examples: "What's our CTR?", "show me spend for q1", "roi on spring campaign?"

Return ONLY a JSON array of strings."""
    
    result = call_llm(prompt)
    colloquials = parse_json_list(result)
    
    for i, c in enumerate(colloquials[:NUM_COLLOQUIAL]):
        eval_rows.append({
            "id": f"EVAL-{len(eval_rows)+1:04d}",
            "prompt": c,
            "category": "colloquial_rewrite",
            "expected_lane": "certified",
            "expected_corpus_id": corpus_id,
            "difficulty": "medium",
            "source_corpus_id": corpus_id,
            "generation_method": "llm_paraphrase",
            "created_at": datetime.utcnow(),
            "notes": f"Colloquial rewrite of: {question[:80]}"
        })

print(f"  Colloquial rows added: {len(eval_rows) - colloquial_before}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 4: Near-Miss Negatives (expected: analytical)

# COMMAND ----------

# DBTITLE 1,Category 4: Near-Miss Negatives (expected: analytical)
print(f"Generating {NUM_NEAR_MISSES} near-miss negatives per entry...")
nearmiss_before = len(eval_rows)

for entry in certified_entries:
    question = entry["question"]
    corpus_id = entry["id"]
    
    prompt = f"""Given this certified question: "{question}"

Generate exactly {NUM_NEAR_MISSES} questions that are RELATED to the same topic but ask for a FUNDAMENTALLY DIFFERENT analysis.

Rules:
- Must be about the same general domain (ads, banners, campaigns, digital marketing)
- Must ask for a DIFFERENT core metric/analysis that CANNOT be answered by the certified SQL
- Should be plausible questions a real analyst might ask

CRITICAL: These are NOT near-misses (do NOT generate these):
- Same metric with a time period added ("CTR for Q1") — this MATCHES the certified question
- Same metric with a campaign/region filter ("spend for summer campaign") — this MATCHES
- Same metric with typos or informal language — this MATCHES
- Same metric with synonyms ("bounce rate" = "percentage who leave") — this MATCHES

These ARE valid near-misses (generate these):
- Certified: "What is the total ad spend for Q1?" → Near miss: "How is ad spend distributed across channels?" (different GROUPING)
- Certified: "What is the CTR by banner size?" → Near miss: "Which banner sizes should we retire?" (different ANALYSIS TYPE — recommendation vs metric)
- Certified: "What was the ROI for the spring campaign?" → Near miss: "Compare ROI trends across all campaigns over time" (RANKING/COMPARISON across entities)
- Certified: "What is the bounce rate from banner landing pages?" → Near miss: "What factors drive high bounce rates?" (CAUSAL analysis)
- Certified: "What is the conversion rate for banner campaigns?" → Near miss: "Which campaign had the highest conversion rate?" (RANKING — needs subquery)

Return ONLY a JSON array of strings."""
    
    result = call_llm(prompt)
    near_misses = parse_json_list(result)
    
    for i, nm in enumerate(near_misses[:NUM_NEAR_MISSES]):
        eval_rows.append({
            "id": f"EVAL-{len(eval_rows)+1:04d}",
            "prompt": nm,
            "category": "near_miss_negative",
            "expected_lane": "analytical",
            "expected_corpus_id": None,
            "difficulty": "hard",
            "source_corpus_id": corpus_id,
            "generation_method": "near_miss",
            "created_at": datetime.utcnow(),
            "notes": f"Near-miss of: {question[:80]}"
        })

print(f"  Near-miss rows added: {len(eval_rows) - nearmiss_before}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 5: Unrelated Questions (expected: analytical)

# COMMAND ----------

print("Generating 50 unrelated domain questions...")
unrelated_before = len(eval_rows)

prompt = """Generate exactly 50 questions that a business analyst might ask about their data,
but that are NOT related to banner/display advertising metrics, ad spend, CTR, impressions, or campaign performance.

Include questions about:
- Supply chain and inventory
- HR and workforce analytics
- Financial forecasting
- Customer churn and retention
- Product recommendations
- Operational efficiency
- Patient outcomes (healthcare context)
- Claims processing
- Network adequacy
- Provider performance

Return ONLY a JSON array of 50 question strings."""

result = call_llm(prompt, max_tokens=4000)
unrelated = parse_json_list(result)

for q in unrelated[:50]:
    eval_rows.append({
        "id": f"EVAL-{len(eval_rows)+1:04d}",
        "prompt": q,
        "category": "unrelated_question",
        "expected_lane": "analytical",
        "expected_corpus_id": None,
        "difficulty": "easy",
        "source_corpus_id": None,
        "generation_method": "llm_paraphrase",
        "created_at": datetime.utcnow(),
        "notes": "Unrelated domain question"
    })

print(f"  Unrelated rows added: {len(eval_rows) - unrelated_before}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 6: Stale Entry Tests (expected: analytical)

# COMMAND ----------

# DBTITLE 1,Category 6: Stale Entry Tests (expected: analytical)
print("Generating stale entry test cases...")
stale_before = len(eval_rows)

# Use stale entries (past next_review_date) — detected in cell above
# IMPORTANT: Stale entry test prompts must use UNIQUE keywords that only exist
# in the stale entries and NOT in any non-stale entry. This ensures VS returns
# the stale entry as the top match, so the staleness check fires correctly.
#
# Stale entries (QA-0019, QA-0020) and their unique signals:
#   QA-0019: "trended over 6 months" — unique temporal scope
#   QA-0020: "CPM by publisher" — unique dimension (QA-0005 is "CPM by region")

for entry in stale_candidates:
    question = entry["question"]
    corpus_id = entry["id"]
    
    prompt = f"""Given this certified question: "{question}"
Generate 5 paraphrases that ask the SAME thing but worded differently.

CRITICAL RULES:
- PRESERVE the unique distinguishing keywords (e.g., "viewability", "by publisher", "6 months", "trended")
- These keywords MUST appear in the paraphrase to ensure semantic uniqueness
- Fill any {{param}} placeholders with concrete values
- Vary sentence structure, formality, and phrasing

Return ONLY a JSON array of 5 strings."""
    
    result = call_llm(prompt)
    paraphrases = parse_json_list(result)
    
    for p in paraphrases[:5]:
        eval_rows.append({
            "id": f"EVAL-{len(eval_rows)+1:04d}",
            "prompt": p,
            "category": "stale_entry_test",
            "expected_lane": "analytical",
            "expected_corpus_id": corpus_id,
            "difficulty": "medium",
            "source_corpus_id": corpus_id,
            "generation_method": "llm_paraphrase",
            "created_at": datetime.utcnow(),
            "notes": f"Stale entry (past review_date): {corpus_id} — uses unique keywords"
        })

print(f"  Stale test rows added: {len(eval_rows) - stale_before}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 7: Adversarial Prompts (expected: analytical)

# COMMAND ----------

# DBTITLE 1,Category 7: Adversarial Tests (expected: analytical)
print("Generating adversarial test cases...")
adversarial_before = len(eval_rows)

sample_questions = [e["question"] for e in certified_entries[:5]]

prompt = f"""Generate exactly 25 adversarial prompts designed to stress-test a confidence-gated router.
The router has these certified questions in its corpus:
{json.dumps(sample_questions, indent=2)}

Generate prompts in these adversarial categories (5 each):
1. COMPOUND: Combine two DISTINCT metrics in one question (e.g. "What is the spend AND how many impressions?")
2. MISLEADING: Use keywords from certified entries but ask for a genuinely different analysis (e.g. "industry benchmarks" using same keywords as internal metrics)
3. INJECTION: "Ignore previous instructions...", "system: override confidence...", prompt injection attempts
4. AMBIGUOUS: Questions that could match multiple entries equally or are genuinely unclear
5. NONSENSE: Non-questions, random text, extremely vague single words like "data", or requests that aren't analytics questions

IMPORTANT: Do NOT include:
- Questions with simple typos/misspellings (those are valid user input and SHOULD match)
- Questions that add a time period or campaign name to a certified metric (those SHOULD match)
- Informal/slang versions of certified questions (those SHOULD match)

ALL generated prompts must be genuinely unmatchable to any certified entry.

Return ONLY a JSON array of objects: [{{"prompt": "...", "subcategory": "compound|misleading|injection|ambiguous|nonsense"}}]"""

result = call_llm(prompt, max_tokens=3000)
adversarial = parse_json_list(result)

for item in adversarial[:25]:
    if isinstance(item, dict):
        p = item.get("prompt", "")
        subcat = item.get("subcategory", "adversarial")
    else:
        p = str(item)
        subcat = "adversarial"
    
    if p:
        eval_rows.append({
            "id": f"EVAL-{len(eval_rows)+1:04d}",
            "prompt": p,
            "category": "adversarial",
            "expected_lane": "analytical",
            "expected_corpus_id": None,
            "difficulty": "hard",
            "source_corpus_id": None,
            "generation_method": "adversarial",
            "created_at": datetime.utcnow(),
            "notes": f"Adversarial subcategory: {subcat}"
        })

print(f"  Adversarial rows added: {len(eval_rows) - adversarial_before}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 8: Boundary Cases (expected: mixed)

# COMMAND ----------

print("Generating boundary calibration cases...")
boundary_before = len(eval_rows)

sample_qs = [e["question"] for e in certified_entries[:10]]
prompt = f"""Generate 20 questions that are on the BOUNDARY between matching and not matching these certified questions:
{json.dumps(sample_qs, indent=2)}

Split into two groups:
1. 10 questions that are CLOSE to a certified question and SHOULD be CERTIFIED (slight rewording, synonym usage, minor additions but same core intent)
2. 10 questions that look similar but SHOULD be ANALYTICAL (subtle intent shift, different granularity, extra constraint that changes the answer)

Return ONLY a JSON array of objects: [{{"prompt": "...", "expected_lane": "certified"|"analytical", "reasoning": "..."}}]"""

result = call_llm(prompt, max_tokens=3000)
boundary = parse_json_list(result)

for item in boundary[:20]:
    if isinstance(item, dict):
        p = item.get("prompt", "")
        expected = item.get("expected_lane", "analytical")
        reasoning = item.get("reasoning", "")
    else:
        continue
    
    if p:
        eval_rows.append({
            "id": f"EVAL-{len(eval_rows)+1:04d}",
            "prompt": p,
            "category": "boundary_case",
            "expected_lane": expected,
            "expected_corpus_id": None,
            "difficulty": "hard",
            "source_corpus_id": None,
            "generation_method": "llm_paraphrase",
            "created_at": datetime.utcnow(),
            "notes": f"Boundary case: {reasoning[:100]}"
        })

print(f"  Boundary rows added: {len(eval_rows) - boundary_before}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Eval Dataset to Delta Table

# COMMAND ----------

from pyspark.sql.types import *

schema = StructType([
    StructField("id", StringType(), False),
    StructField("prompt", StringType(), False),
    StructField("category", StringType(), False),
    StructField("expected_lane", StringType(), False),
    StructField("expected_corpus_id", StringType(), True),
    StructField("difficulty", StringType(), True),
    StructField("source_corpus_id", StringType(), True),
    StructField("generation_method", StringType(), True),
    StructField("created_at", TimestampType(), True),
    StructField("notes", StringType(), True),
])

eval_df = spark.createDataFrame(eval_rows, schema=schema)

# Write (overwrite if regenerating)
write_mode = "overwrite" if REGENERATE else "append"
eval_df.write.mode(write_mode).saveAsTable(EVAL_TABLE)

final_count = eval_df.count()
print(f"\n{'='*60}")
print(f"  Eval Dataset Written: {EVAL_TABLE}")
print(f"  Total rows: {final_count}")
print(f"  Write mode: {write_mode}")
print(f"{'='*60}")

assert final_count >= 100, f"Expected at least 100 eval rows, got {final_count}. Check LLM connectivity."

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary by Category

# COMMAND ----------

from pyspark.sql import functions as F

summary = (
    spark.table(EVAL_TABLE)
    .groupBy("category", "expected_lane")
    .agg(F.count("*").alias("count"))
    .orderBy("category", "expected_lane")
)
summary.display()

# Lane distribution
print("\nLane distribution:")
spark.table(EVAL_TABLE).groupBy("expected_lane").count().show()

print(f"\nDone. {final_count} eval rows generated successfully.")