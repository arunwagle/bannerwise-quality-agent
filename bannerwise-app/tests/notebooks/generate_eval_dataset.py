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

import os

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

corpus_df = spark.table(CORPUS_TABLE)
corpus_entries = corpus_df.collect()
print(f"Loaded {len(corpus_entries)} corpus entries")

# Separate by status for staleness tests
certified_entries = [r for r in corpus_entries if r["status"] == "certified"]
stale_candidates = [r for r in corpus_entries if r["status"] == "expired"]
print(f"  Certified: {len(certified_entries)}")
print(f"  Expired (for staleness tests): {len(stale_candidates)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## LLM Helper

# COMMAND ----------

import json
from openai import OpenAI

def get_llm_client():
    """Create OpenAI client pointing to Databricks Foundation Model."""
    return OpenAI(
        api_key=os.environ.get("DATABRICKS_TOKEN", ""),
        base_url=f"{os.environ.get('DATABRICKS_HOST', '')}/serving-endpoints"
    )

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
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])
        if text.startswith("json"):
            text = text[4:]
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

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 1: Exact Paraphrases (expected: certified)

# COMMAND ----------

from datetime import datetime
import uuid

eval_rows = []

print(f"Generating {NUM_PARAPHRASES} paraphrases per certified entry...")
for entry in certified_entries:
    question = entry["question"]
    corpus_id = entry["id"]
    
    prompt = f"""Given this certified question: "{question}"

Generate exactly {NUM_PARAPHRASES} paraphrases that ask the EXACT same thing using different words.

Rules:
- Preserve the original intent completely
- Vary sentence structure, vocabulary, and phrasing
- Include formal, casual, and question-with-context variations
- If the question has parameters (like campaign names or time periods), keep them but reword around them

Return a JSON array of strings. Example: ["paraphrase 1", "paraphrase 2"]"""
    
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

print(f"Generating {NUM_PARAM_VARIATIONS} parameter variations per parameterized entry...")
param_count_before = len(eval_rows)

for entry in certified_entries:
    params = entry["parameters"]
    if not params or len(params) == 0:
        continue
    
    question = entry["question"]
    corpus_id = entry["id"]
    
    prompt = f"""Given this certified question: "{question}"
Which uses these parameters: {params}

Generate exactly {NUM_PARAM_VARIATIONS} variations of this question that ask the same thing but with DIFFERENT parameter values.

For example, if the original asks about "Q1 2025", generate versions asking about "Q3 2024", "last month", "this year", etc.
If it mentions a campaign name, substitute other plausible campaign names like "holiday_promo", "summer_blast", "q4_push".

The intent must remain the same — only the parameter values change.

Return a JSON array of strings."""
    
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
            "notes": f"Param variation of: {question[:80]} | params: {params}"
        })

print(f"  Parameter variation rows added: {len(eval_rows) - param_count_before}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 3: Colloquial Rewrites (expected: certified)

# COMMAND ----------

print(f"Generating {NUM_COLLOQUIAL} colloquial rewrites per entry...")
colloquial_before = len(eval_rows)

for entry in certified_entries:
    question = entry["question"]
    corpus_id = entry["id"]
    
    prompt = f"""Given this formal certified question: "{question}"

Generate exactly {NUM_COLLOQUIAL} casual/colloquial rewrites — how a real user would quickly type this in a chat interface.

Rules:
- Use informal language, abbreviations, shorthand
- May drop articles, use contractions, be terse
- Must still convey the EXACT same intent
- Examples: "What's our CTR?", "show me spend for q1", "roi on spring campaign?"

Return a JSON array of strings."""
    
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

print(f"Generating {NUM_NEAR_MISSES} near-miss negatives per entry...")
nearmiss_before = len(eval_rows)

for entry in certified_entries:
    question = entry["question"]
    corpus_id = entry["id"]
    
    prompt = f"""Given this certified question: "{question}"

Generate exactly {NUM_NEAR_MISSES} questions that are RELATED to the same topic but ask for something DIFFERENT.

Rules:
- Must be about the same general domain (ads, banners, campaigns, digital marketing)
- Must have a CLEARLY different intent (different metric, different aggregation, different scope, different granularity)
- Should be plausible questions a real analyst might ask
- The confidence gate should NOT match these to the certified entry

Examples of "near miss":
- Certified: "What is the total ad spend for Q1?" → Near miss: "How is ad spend distributed across channels?"
- Certified: "What is the CTR by banner size?" → Near miss: "Which banner sizes should we retire?"

Return a JSON array of strings."""
    
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
but that are NOT related to banner/display advertising metrics.

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

Return a JSON array of 50 question strings."""

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

print("Generating stale entry test cases...")
stale_before = len(eval_rows)

# Use expired entries + force-stale certified entries (questions that match but should be blocked)
for entry in stale_candidates:
    question = entry["question"]
    corpus_id = entry["id"]
    
    # Generate 2-3 paraphrases of stale questions
    prompt = f"""Given this question: "{question}"
Generate 3 paraphrases that ask the exact same thing.
Return a JSON array of strings."""
    
    result = call_llm(prompt)
    paraphrases = parse_json_list(result)
    
    for p in paraphrases[:3]:
        eval_rows.append({
            "id": f"EVAL-{len(eval_rows)+1:04d}",
            "prompt": p,
            "category": "stale_entry_test",
            "expected_lane": "analytical",
            "expected_corpus_id": None,
            "difficulty": "medium",
            "source_corpus_id": corpus_id,
            "generation_method": "llm_paraphrase",
            "created_at": datetime.utcnow(),
            "notes": f"Stale entry (expired): {corpus_id} | next_review_date in past"
        })

# Also add some that match certified entries but we'll mark with stale dates
# (These test the staleness_check logic when the entry WOULD match but is stale)
for entry in certified_entries[-3:]:  # Last 3 certified entries as staleness simulation
    eval_rows.append({
        "id": f"EVAL-{len(eval_rows)+1:04d}",
        "prompt": entry["question"],
        "category": "stale_entry_test",
        "expected_lane": "analytical",
        "expected_corpus_id": None,
        "difficulty": "hard",
        "source_corpus_id": entry["id"],
        "generation_method": "manual",
        "created_at": datetime.utcnow(),
        "notes": f"Exact match but entry marked stale for test (simulated past review date)"
    })

print(f"  Stale test rows added: {len(eval_rows) - stale_before}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Category 7: Adversarial Prompts (expected: analytical)

# COMMAND ----------

print("Generating adversarial test cases...")
adversarial_before = len(eval_rows)

# Get a few certified questions to reference in adversarial prompts
sample_questions = [e["question"] for e in certified_entries[:5]]

prompt = f"""Generate exactly 25 adversarial prompts designed to stress-test a confidence-gated router.
The router has these certified questions in its corpus:
{json.dumps(sample_questions, indent=2)}

Generate prompts in these adversarial categories:
1. Compound questions combining two different intents (5 prompts)
2. Questions with misleading keywords from certified entries but different intent (5 prompts)
3. Prompt injection attempts like "ignore previous instructions..." (5 prompts)
4. Extremely ambiguous questions that could match multiple entries (5 prompts)
5. Edge cases: very short (1-2 words), very long (50+ words), typos, broken English (5 prompts)

The router should route ALL of these to the analytical lane (they should NOT be matched).

Return a JSON array of objects with "prompt" and "subcategory" fields.
Example: [{{"prompt": "...", "subcategory": "compound"}}]"""

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

# These are cases that should land near the threshold (0.85) — some should pass, some shouldn't
prompt = f"""Generate 20 questions that are on the BOUNDARY between matching and not matching these certified questions:
{json.dumps(sample_questions[:10], indent=2)}

Split into two groups:
1. 10 questions that are CLOSE to a certified question but should still be CERTIFIED (slight rewording, synonym usage, minor additions)
2. 10 questions that look similar but should be ANALYTICAL (subtle intent shift, different granularity, added constraint that changes the answer)

Return a JSON array of objects: [{{"prompt": "...", "expected_lane": "certified"|"analytical", "reasoning": "..."}}]"""

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
            "expected_corpus_id": None if expected == "analytical" else certified_entries[0]["id"],
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

print(f"\n{'='*60}")
print(f"  Eval Dataset Written: {EVAL_TABLE}")
print(f"  Total rows: {eval_df.count()}")
print(f"  Write mode: {write_mode}")
print(f"{'='*60}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary by Category

# COMMAND ----------

from pyspark.sql import functions as F

summary = (
    eval_df
    .groupBy("category", "expected_lane")
    .agg(
        F.count("*").alias("count"),
        F.countDistinct("source_corpus_id").alias("source_entries")
    )
    .orderBy("category", "expected_lane")
)
summary.display()

# Category totals
print("\nCategory totals:")
eval_df.groupBy("category").count().orderBy("category").show(truncate=False)

# Lane distribution
print("Lane distribution:")
eval_df.groupBy("expected_lane").count().show()
