# Provenance Guard — Planning Document
## AI201 · Project 4

---

## Architecture

### Narrative

Provenance Guard is a Flask backend that accepts free-text submissions and produces a human/AI authorship signal by combining two independent detection mechanisms. Every inbound request first passes through an input validation layer that enforces schema requirements (non-empty text, reasonable length bounds) and through Flask-Limiter rate guards (10 requests per minute, 100 per day per remote address) before any expensive work begins. Validated text is then dispatched in sequence to two signal producers: the Groq LLM Signal, which prompts a Groq-hosted language model to reason about linguistic markers of AI authorship, and the Stylometric Signal, which computes local statistical features of the text (sentence length variance, type-token ratio, and punctuation density). Neither signal alone determines the outcome; both are passed to a Confidence Engine that applies a weighted average and maps the resulting score onto a three-state label via fixed thresholds.

The Confidence Engine outputs a numeric score in [0, 1] (0 = almost certainly human, 1 = almost certainly AI) along with per-signal weights. A Label Generator converts that score to one of three human-readable states: "Likely Human" (score < 0.35), "Uncertain" (0.35 ≤ score < 0.65), or "Likely AI" (score ≥ 0.65). Every completed submission — including its content hash, timestamp, signals, score, label, and status — is written synchronously to an in-memory audit log (a Python list backed by an optional append-only JSONL file for persistence across restarts). The same audit log is the source of truth for the `/log` endpoint and for the `/appeal` workflow, which allows a client to flag a submission for human review by content ID, updating its status from `"active"` to `"under_review"`.

The appeal pathway is deliberately lightweight: it looks up the existing audit entry by `content_id`, rejects unknown IDs with a 404, and writes a status-change record rather than re-running detection. This design keeps the detection pipeline and the review pipeline cleanly separated — a re-analysis, if ever needed, would submit fresh content rather than mutating a historical record. All three endpoints return JSON with a consistent structure, making the API straightforward to consume from any downstream tool.

---

### Component Responsibilities

**Flask Application (`app.py`)**
- Registers routes for `POST /submit`, `POST /appeal`, and `GET /log`
- Attaches Flask-Limiter to all routes (10/min, 100/day per IP)
- Wires together the pipeline components in correct order
- Returns consistent JSON responses; handles errors with appropriate HTTP status codes (400, 404, 429, 500)

**Input Validator**
- Checks that `text` field is present and is a non-empty string
- Enforces minimum length (≥ 20 characters) and maximum length (≤ 10,000 characters)
- Returns structured error messages on failure; returns cleaned text on success

**Groq LLM Signal (`signals/groq_signal.py`)**
- Sends text to Groq API (model: `llama3-8b-8192`)
- System prompt instructs the model to return `{"ai_score": float}` based on four linguistic dimensions
- Parses and validates the response; falls back to 0.5 (neutral) on API failure or malformed response
- Returns score in [0.0, 1.0]

**Stylometric Signal (`signals/stylometric_signal.py`)**
- Computes three local text features: sentence length variance, type-token ratio, punctuation density
- Normalizes each feature to [0, 1]
- Weighted combination: 50% SLV + 30% TTR + 20% PD
- Returns score in [0.0, 1.0]; returns 0.5 (neutral) for texts under 2 sentences or 10 words

**Confidence Engine (`engine/confidence.py`)**
- Receives both signal scores
- Applies configurable weights (default: Groq LLM 60%, Stylometric 40%)
- Returns combined score in [0.0, 1.0]

**Label Generator (`engine/labels.py`)**
- score < 0.35 → `"Likely Human"`
- 0.35 ≤ score < 0.65 → `"Uncertain"`
- score ≥ 0.65 → `"Likely AI"`

**Audit Log (`audit/log.py`)**
- Maintains an in-memory list of audit records (append-only)
- Optionally persists records to `audit_log.jsonl` for restart durability
- Exposes `append(record)`, `get_all()`, and `get_by_id(content_id)` operations
- Thread safety via `threading.Lock` around writes

**Rate Limiter (Flask-Limiter)**
- Limits `POST /submit` to 10 requests/minute and 100 requests/day per remote IP
- Returns HTTP 429 with JSON error body on limit breach

---

### ASCII Architecture Diagram

#### `POST /submit` Request Flow

```
  Client
    |
    | POST /submit  {"text": "...", "creator_id": "..."}
    v
+-------------------+
|  Flask-Limiter    |  10/min, 100/day per IP
|  Rate Guard       |  --> 429 if exceeded
+-------------------+
    |
    v
+-------------------+
|  Input Validator  |  schema check, length bounds
+-------------------+  --> 400 if invalid
    |
    | cleaned text
    v
+-------------------------------+
|       Detection Pipeline      |
|                               |
|  +------------------------+   |
|  | Groq LLM Signal        |   |
|  | Calls Groq API         |   |
|  | Returns score [0,1]    |   |
|  +----------+-------------+   |
|             |                 |
|  +----------+-------------+   |
|  | Stylometric Signal     |   |
|  | Local feature compute  |   |
|  | Returns score [0,1]    |   |
|  +----------+-------------+   |
|             |                 |
|  +----------v-------------+   |
|  | Confidence Engine      |   |
|  | Weighted avg: 60/40    |   |
|  | Returns combined score |   |
|  +----------+-------------+   |
|             |                 |
|  +----------v-------------+   |
|  | Label Generator        |   |
|  | <0.35  → Likely Human  |   |
|  | <0.65  → Uncertain     |   |
|  | >=0.65 → Likely AI     |   |
|  +----------+-------------+   |
+-------------|------------------+
              |
              v
+-------------------+
|   Audit Log       |
|   append record   |
|   write to .jsonl |
+-------------------+
              |
              v
  JSON Response → Client
  {content_id, label, confidence, signals, status, timestamp}
```

#### `POST /appeal` Request Flow

```
  Client
    |
    | POST /appeal  {"content_id": "...", "creator_reasoning": "..."}
    v
+-------------------+
|  Flask-Limiter    |  10/min, 100/day per IP --> 429
+-------------------+
    |
    v
+-------------------+
|  Input Validator  |  presence check on content_id + creator_reasoning
+-------------------+
    |
    v
+-------------------+
|  Audit Log Lookup |  get_by_id(content_id) --> 404 if not found
+-------------------+
    |
    | existing record found
    v
+-------------------+
|  Status Update    |  set status = "under_review"
|                   |  append appeal event to log
+-------------------+
    |
    v
  JSON Response → Client
  {content_id, status: "under_review", previous_label, timestamp}
```

#### `GET /log` Request Flow

```
  Client
    |
    | GET /log  [?creator_id=X]
    v
+-------------------+
|   Audit Log       |
|   get_all()       |
+-------------------+
    |
    v
  JSON Response → Client
  {count, entries: [...]}
```

---

## Detection Signals

Two independent signals are combined to produce a final AI-likelihood score. Independence is genuine: Signal 1 relies on an external LLM's semantic reasoning; Signal 2 relies only on surface-level statistical properties of the text, computed locally with no ML model.

---

### Signal 1 — Groq LLM Classification

#### Overview

The Groq API is called with a lightweight model (`llama3-8b-8192`) to perform a direct semantic judgment on the submitted text. The LLM is asked to reason across four dimensions and return a single numeric score.

#### System Prompt

```
You are an AI writing detector. Your sole task is to analyze text and output a
single JSON object — nothing else.

Evaluate the text across these four dimensions:

1. Semantic coherence: Does every sentence logically connect to the next with no
   abrupt topic jumps? AI text tends toward uniform, over-smooth transitions.

2. AI writing characteristics: Look for hedging phrases ("it is important to
   note", "in conclusion", "it is worth mentioning"), bullet-point sentence
   structures embedded in prose, and unnaturally balanced paragraph lengths.

3. Formality register: Is the register artificially consistent throughout, with
   no colloquialisms, contractions, or register shifts? Human writing shows
   natural register variation.

4. Repetition patterns: Are the same sentence-opening patterns, conjunctions, or
   transitional phrases reused at a rate higher than natural human writing?

Return ONLY this JSON (no surrounding text, no explanation):
{"ai_score": <float between 0.0 and 1.0>}

Where 0.0 means almost certainly human-written and 1.0 means almost certainly
AI-generated.
```

#### User Prompt Template

```
Analyze the following text and return your JSON score:

---
{text}
---
```

#### Implementation Notes

```python
import os, json
from groq import Groq

def groq_llm_score(text: str) -> float:
    """Return 0.0–1.0 AI likelihood via Groq LLM classification."""
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    try:
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": USER_PROMPT.format(text=text)},
            ],
            temperature=0.0,
            max_tokens=32,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
        return max(0.0, min(1.0, float(data["ai_score"])))
    except Exception:
        return 0.5  # neutral fallback on any failure
```

#### Blind Spots

- **Academic/formal human writing** uses same markers (hedging, smooth transitions, consistent register) — false positives
- **Short texts** (< ~80 words) give insufficient signal
- **Non-English text** — behavior undefined

---

### Signal 2 — Stylometric Analysis

#### Overview

A pure-Python algorithm computes three statistical surface features of the text. No external API or ML model is used.

#### Metrics

| Metric | AI Pattern | Normalization |
|---|---|---|
| **Sentence Length Variance (SLV)** | AI: uniformly medium-length sentences (low std_dev 1–4) | Inverted sigmoid centered at std_dev=4 |
| **Type-Token Ratio (TTR)** | AI: artificially high vocabulary variety (TTR 0.65–0.85) | Excess above 0.65 normalized over 0.20 range |
| **Punctuation Density (PD)** | AI: avoids complex punctuation (PD < 0.04) | Shortfall below 0.04 normalized over 0.04 range |

#### Pseudocode

```
function stylometric_score(text):
    sentences = split_on_sentence_boundaries(text)
    words     = tokenize_words(text)

    if len(sentences) < 2 or len(words) < 10:
        return 0.5  # insufficient signal

    # Sentence Length Variance
    sent_lengths = [word_count(s) for s in sentences]
    std_dev      = population_std_dev(sent_lengths)
    slv_score    = 1.0 / (1.0 + exp(std_dev - 4.0))   # low variance → high AI score

    # Type-Token Ratio
    ttr          = len(unique(words)) / len(words)
    ttr_score    = min(1.0, max(0.0, ttr - 0.65) / 0.20)

    # Punctuation Density
    pd           = count_punct_chars(text) / len(text)
    pd_score     = min(1.0, max(0.0, 0.04 - pd) / 0.04)

    return clamp((0.50 * slv_score) + (0.30 * ttr_score) + (0.20 * pd_score), 0.0, 1.0)
```

#### Python Implementation

```python
import re, math

def stylometric_score(text: str) -> float:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    words     = re.findall(r"[a-zA-Z']+", text.lower())

    if len(sentences) < 2 or len(words) < 10:
        return 0.5

    sent_lengths = [len(re.findall(r"[a-zA-Z']+", s)) for s in sentences]
    mean_len     = sum(sent_lengths) / len(sent_lengths)
    std_dev      = math.sqrt(sum((l - mean_len)**2 for l in sent_lengths) / len(sent_lengths))
    slv_score    = 1.0 / (1.0 + math.exp(std_dev - 4.0))

    ttr       = len(set(words)) / len(words)
    ttr_score = min(1.0, max(0.0, ttr - 0.65) / 0.20)

    punct     = sum(1 for c in text if not c.isalnum() and c != ' ')
    pd        = punct / max(1, len(text))
    pd_score  = min(1.0, max(0.0, 0.04 - pd) / 0.04)

    return max(0.0, min(1.0, 0.50 * slv_score + 0.30 * ttr_score + 0.20 * pd_score))
```

#### Blind Spots

- **Edited AI content** — human edits destroy all three metrics
- **Poetry** — extreme SLV and unusual punctuation cause false negatives
- **Short texts** — neutral fallback triggered below 2 sentences

---

### Score Combination

#### Weighting Rationale

| Signal | Weight | Justification |
|---|---|---|
| Groq LLM Classification | **60%** | Semantic reasoning captures higher-level patterns invariant to surface editing; generalizes across domains |
| Stylometric Analysis | **40%** | Fast, free, fully deterministic; independent check when LLM is unavailable |

#### Combination Formula

```python
def combine_scores(groq: float, stylo: float, w_groq=0.60, w_stylo=0.40) -> float:
    combined = (w_groq * groq) + (w_stylo * stylo)
    return round(max(0.0, min(1.0, combined)), 4)
```

If either signal errors, it falls back to 0.5 so the other signal still contributes.

| Groq | Stylo | Combined | Result |
|---|---|---|---|
| 0.90 | 0.80 | 0.86 | Likely AI |
| 0.70 | 0.30 | 0.54 | Uncertain |
| 0.20 | 0.10 | 0.16 | Likely Human |
| 0.50 (error) | 0.75 | 0.60 | Uncertain (Groq unavailable) |

---

## Confidence Scoring

### Score Ranges and Labels

| Score Range | Label | Internal Attribution |
|---|---|---|
| 0.00 – 0.34 | Likely Human | `"human"` |
| 0.35 – 0.64 | Uncertain | `"uncertain"` |
| 0.65 – 1.00 | Likely AI | `"ai"` |

The "Uncertain" band is intentionally 30 points wide to absorb statistical noise and genuine mixed-authorship cases. The system under-classifies (favors uncertainty) rather than over-classifies, because false positives in this domain are institutionally dangerous.

### Why False Positives Are Dangerous

In content moderation contexts, a false positive (human text flagged as AI) can:
1. Unjustly suppress a human creator's voice and reputation
2. Create a chilling effect on legitimate writing in formal registers
3. Erode institutional trust in the detection system
4. Expose the platform to legal and defamation liability

This asymmetry of harm means the system should require strong evidence before assigning an "AI" label.

### Why Uncertainty Exists

Detection signals exist on a spectrum with no clean human/AI boundary:
- Mixed authorship (AI-drafted, human-edited) is common and real
- The same stylistic patterns appear in both formal human writing and AI output
- Short texts produce near-chance scores regardless of origin
- Every threshold is a policy decision, not a discovered natural boundary

### Why Confidence Is Not Binary

A binary AI/human verdict would:
- Suppress genuine ambiguity rather than communicate it
- Prevent callers from applying domain-appropriate thresholds
- Misrepresent the statistical nature of detection

The 0.0–1.0 score plus three-label mapping lets callers decide their own risk tolerance.

### Worked Examples

#### Example 1 — High AI Confidence (score: 0.85)

Text: *"The mitochondria serves as the powerhouse of the cell, facilitating ATP synthesis through oxidative phosphorylation. It is important to note that this process is essential for cellular energy production. In conclusion, understanding mitochondrial function is key to appreciating cellular metabolism."*

| Signal | Score | Reason |
|---|---|---|
| Groq LLM | 0.90 | "It is important to note," "In conclusion" — classic AI hedging phrases; uniform register |
| Stylometric | 0.76 | Low SLV (sentences are similar length), high TTR, low punctuation density |
| Combined | 0.85 | Both signals agree strongly |

**Label: Likely AI**

---

#### Example 2 — High Human Confidence (score: 0.15)

Text: *"honestly i dont even know where to start lol. my cat knocked over my coffee this morning and now im writing this with a paper towel stuck to my keyboard. anyway yeah the sourdough starter is doing fine i guess"*

| Signal | Score | Reason |
|---|---|---|
| Groq LLM | 0.08 | No AI markers; informal register, personal narrative, intentional grammatical looseness |
| Stylometric | 0.11 | High SLV (mixed lengths), TTR below AI threshold, punctuation density near zero |
| Combined | 0.10 | Both signals agree strongly on human origin |

**Label: Likely Human**

---

#### Example 3 — Borderline Uncertain (score: 0.52)

Text: *"When approaching system design interviews, it helps to frame your answer around scalability, reliability, and maintainability. I've found that drawing out the architecture first — even a rough sketch — forces you to think through data flow before writing a single line of code."*

| Signal | Score | Reason |
|---|---|---|
| Groq LLM | 0.61 | Organized structure suggests AI; but personal anecdote ("I've found") suggests human |
| Stylometric | 0.38 | Moderate SLV; em-dash raises punctuation density into human range |
| Combined | 0.52 | Signals disagree; genuine ambiguity |

**Label: Uncertain** — this is an honest answer, not a system failure.

---

## Transparency Labels

### Label Definitions

#### "Likely AI-Generated" — triggered at score ≥ 0.65

**Display tag:** `AI-Generated`

**User-facing explanation:**
> This content shows strong signs of being written by an AI tool rather than a person. You may want to verify key facts with an additional source before relying on it.

**Recommended action:** Treat with extra care. Check important facts. Do not cite as a primary human-authored source.

---

#### "Likely Human-Written" — triggered at score ≤ 0.34

**Display tag:** `Human-Written`

**User-facing explanation:**
> This content shows strong signs of being written by a person. It may still contain errors or bias, so normal critical reading still applies.

**Recommended action:** No special steps needed. Evaluate as you would any written content.

---

#### "Uncertain — Human Review Recommended" — triggered at 0.35 ≤ score ≤ 0.64

**Display tag:** `Origin Unclear`

**User-facing explanation:**
> This content could have been written by a person, an AI tool, or a combination of both. A human reviewer should check it before it is used in contexts where authorship matters.

**Recommended action:** Do not publish or rely on this content in authorship-sensitive contexts until a person has reviewed it.

---

### Label Generation Rules

```python
def assign_label(score: float) -> str:
    if score < 0.35:
        return "Likely Human"
    elif score < 0.65:
        return "Uncertain"
    else:
        return "Likely AI"

def assign_attribution(score: float) -> str:
    if score < 0.35:
        return "human"
    elif score < 0.65:
        return "uncertain"
    else:
        return "ai"
```

### Why Plain Language

Labels use plain, everyday language because:
- **Equity**: non-technical readers (students, creators, journalists) must understand what the label means without a glossary
- **Accessibility**: hedged phrasing ("Likely") accurately communicates probabilistic nature — no false certainty
- **Trust calibration**: "Origin Unclear" is less alarming than "Flagged" while still prompting review

---

## Appeals Workflow

### Overview

The appeal workflow allows a creator to dispute an attribution decision. The original decision is never overwritten; appeals create new log entries and update the record's status.

### Appeal Submission

`POST /appeal` requires:
- `content_id` (string): the UUID of the flagged content
- `creator_reasoning` (string): the creator's explanation for why the label is incorrect

### System Behavior on Receipt

1. Look up original content by `content_id` → 404 if not found
2. Snapshot original decision fields (label, confidence, scores)
3. Update status from `"active"` to `"under_review"`
4. Write appeal event to audit log (append-only, does not overwrite original)
5. Return confirmation with updated status

### Appeal Lifecycle (State Diagram)

```
          POST /appeal
              |
              v
        +------------+
        |  submitted  |
        +------+------+
               |  appeal logged, status = under_review
               v
        +------------+
        | under_review|
        +------+------+
               |
       +--------+--------+
       |                 |
       v                 v
  +---------+       +-----------+
  | upheld  |       | overturned|
  +---------+       +-----------+
       |                 |
       +--------+--------+
                |
                v
          +----------+
          | resolved |
          +----------+
```

### Valid Status Transitions

| From | Event | To |
|---|---|---|
| `active` | appeal submitted | `under_review` |
| `under_review` | reviewer upholds | `resolved` |
| `under_review` | reviewer overturns | `resolved` |

### Error Handling

| Condition | Response |
|---|---|
| `content_id` not found | 404 `content_not_found` |
| Missing `creator_reasoning` | 400 `missing_fields` |
| Empty `creator_reasoning` | 422 `invalid_input` |
| Duplicate open appeal | 409 `appeal_already_open` |

### Reviewer View Data Structure

When a reviewer examines an appeal, they see:

```json
{
  "content_id": "uuid",
  "creator_id": "string",
  "original_decision": {
    "label": "Likely AI",
    "confidence": 0.82,
    "llm_score": 0.85,
    "stylometric_score": 0.79,
    "timestamp": "ISO-8601"
  },
  "appeal": {
    "creator_reasoning": "string",
    "appeal_timestamp": "ISO-8601"
  },
  "text_preview": "first 100 chars...",
  "audit_trail": []
}
```

---

## API Contract

### POST /submit

**Request body:**
```json
{
  "text": "string (20–10,000 characters, required)",
  "creator_id": "string (required)"
}
```

**Success response — HTTP 200:**
```json
{
  "content_id": "550e8400-e29b-41d4-a716-446655440000",
  "attribution": "ai",
  "confidence": 0.85,
  "label": "Likely AI",
  "signals": {
    "groq_llm": 0.90,
    "stylometric": 0.76
  },
  "status": "active",
  "timestamp": "2026-06-23T14:32:01Z"
}
```

**Error responses:**

| Status | Code | Condition |
|---|---|---|
| 400 | `missing_fields` | `text` or `creator_id` absent |
| 400 | `invalid_input` | `text` empty or too short/long |
| 429 | `rate_limited` | Limit exceeded |
| 500 | `upstream_failure` | Groq API failure (stylometric still runs) |

---

### POST /appeal

**Request body:**
```json
{
  "content_id": "550e8400-e29b-41d4-a716-446655440000",
  "creator_reasoning": "I wrote this myself for my communications course final."
}
```

**Success response — HTTP 200:**
```json
{
  "status": "appeal_received",
  "content_id": "550e8400-e29b-41d4-a716-446655440000",
  "previous_label": "Likely AI",
  "message": "Your appeal has been logged. The content is now marked as under_review."
}
```

**Error responses:**

| Status | Code | Condition |
|---|---|---|
| 400 | `missing_fields` | `content_id` or `creator_reasoning` absent |
| 404 | `content_not_found` | `content_id` not in audit log |
| 409 | `appeal_already_open` | Duplicate open appeal |
| 429 | `rate_limited` | Limit exceeded |

---

### GET /log

**Optional query parameter:** `?creator_id=X` to filter by creator

**Success response — HTTP 200:**
```json
{
  "count": 2,
  "entries": [
    {
      "content_id": "uuid",
      "creator_id": "string",
      "attribution": "ai",
      "confidence": 0.85,
      "llm_score": 0.90,
      "stylometric_score": 0.76,
      "label": "Likely AI",
      "status": "active",
      "timestamp": "2026-06-23T14:32:01Z",
      "text_preview": "first 100 chars..."
    }
  ]
}
```

Returns `[]` entries (not a 404) when no matches found.

---

## Audit Log Design

### Schema

#### Attribution Entry

| Field | Type | Description |
|---|---|---|
| `timestamp` | ISO 8601 string | UTC wall-clock time entry was recorded |
| `content_id` | UUID v4 string | Stable identifier for submitted content |
| `creator_id` | string | Identifier of submitting creator |
| `attribution` | `"human"` \| `"ai"` \| `"uncertain"` | Final attribution label |
| `confidence` | float 0.0–1.0 | Ensemble confidence in attribution |
| `llm_score` | float 0.0–1.0 | Raw AI-likelihood from Groq signal |
| `stylometric_score` | float 0.0–1.0 | Raw AI-likelihood from stylometric signal |
| `status` | `"active"` \| `"under_review"` \| `"resolved"` | Lifecycle state |
| `text_preview` | string ≤ 100 chars | Truncated excerpt for human review |

#### Appeal Event Entry

Inherits all attribution fields plus:

| Field | Type | Description |
|---|---|---|
| `event_type` | `"appeal_submitted"` | Discriminator marking this as appeal event |
| `creator_reasoning` | string | Creator's free-text explanation |
| `appeal_timestamp` | ISO 8601 string | UTC time appeal was received |

### Example Log Entries

#### Entry 1 — High-Confidence AI Detection

```json
{
  "timestamp": "2026-06-23T08:14:02Z",
  "content_id": "a1b2c3d4-0001-4e5f-9a8b-111111111111",
  "creator_id": "user_raphael_77",
  "attribution": "ai",
  "confidence": 0.97,
  "llm_score": 0.96,
  "stylometric_score": 0.98,
  "status": "active",
  "text_preview": "The mitochondria serves as the powerhouse of the cell, facilitating ATP synthesis thro"
}
```

#### Entry 2 — High-Confidence Human Detection

```json
{
  "timestamp": "2026-06-23T09:03:47Z",
  "content_id": "a1b2c3d4-0002-4e5f-9a8b-222222222222",
  "creator_id": "user_priya_m",
  "attribution": "human",
  "confidence": 0.93,
  "llm_score": 0.08,
  "stylometric_score": 0.11,
  "status": "active",
  "text_preview": "honestly i dont even know where to start lol. my cat knocked over my coffee this mornin"
}
```

#### Entry 3 — Borderline Uncertain Case

```json
{
  "timestamp": "2026-06-23T10:47:19Z",
  "content_id": "a1b2c3d4-0003-4e5f-9a8b-333333333333",
  "creator_id": "user_devlin_k",
  "attribution": "uncertain",
  "confidence": 0.54,
  "llm_score": 0.61,
  "stylometric_score": 0.44,
  "status": "under_review",
  "text_preview": "When approaching system design interviews, it helps to frame your answer around scalabi"
}
```

#### Entry 4 — AI Detection That Received an Appeal

```json
{
  "timestamp": "2026-06-23T11:22:55Z",
  "content_id": "a1b2c3d4-0004-4e5f-9a8b-444444444444",
  "creator_id": "user_fatima_al",
  "attribution": "ai",
  "confidence": 0.82,
  "llm_score": 0.85,
  "stylometric_score": 0.79,
  "status": "under_review",
  "text_preview": "In conclusion, the three pillars of effective communication are clarity, consistency, an"
}
```

#### Entry 5 — Appeal Event (Linked to Entry 4)

```json
{
  "timestamp": "2026-06-23T11:22:55Z",
  "content_id": "a1b2c3d4-0004-4e5f-9a8b-444444444444",
  "creator_id": "user_fatima_al",
  "attribution": "ai",
  "confidence": 0.82,
  "llm_score": 0.85,
  "stylometric_score": 0.79,
  "status": "under_review",
  "text_preview": "In conclusion, the three pillars of effective communication are clarity, consistency, an",
  "event_type": "appeal_submitted",
  "creator_reasoning": "This essay was written entirely by me as a final assignment for my communications course. The formal tone is intentional and required by the rubric.",
  "appeal_timestamp": "2026-06-23T14:05:33Z"
}
```

### Design Notes

- **Append-only.** Entries are never edited or deleted. Corrections are expressed as new entries.
- **`content_id` as join key.** All entries sharing a `content_id` form the complete history of a submission.
- **`text_preview` capped at 100 chars** to limit PII exposure in log storage.
- **UTC throughout.** All timestamps stored as ISO 8601 with `Z` suffix.

---

## Rate Limiting

### Configuration

```python
from flask import Flask, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per day", "10 per minute"],
    storage_uri="memory://",
)

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "error": "rate_limited",
        "message": "Too many requests. Please wait before submitting again.",
        "retry_after_seconds": e.retry_after if hasattr(e, 'retry_after') else 60
    }), 429
```

### Why 10/minute

- Each call triggers a paid Groq inference — 10/min already allows 600 Groq calls/hour per IP
- Automated bots fire in bursts; this cap blocks scripts while human users (1–3/min) are unaffected
- Any legitimate integration hitting this cap should be batching submissions

### Why 100/day

- Even heavy creators publish 5–30 pieces/day; 100 is a generous ceiling
- Caps per-IP daily Groq cost exposure without requiring API key issuance
- Counter resets at midnight UTC

### Storage Backend Recommendation

| Environment | Backend | Notes |
|---|---|---|
| Development | `memory://` | Zero setup; not multi-worker safe |
| Single-server prod | `redis://localhost:6379` | Atomic INCR + TTL expiry; correct under Gunicorn |
| Multi-instance prod | Managed Redis URI | Shared state across workers |

---

## Edge Cases & Known Limitations

### Edge Case 1: Poetry

**Why detection fails:** Poetry breaks all prose conventions. Line breaks create artificially short "sentences," extreme vocabulary choices inflate TTR.

**Signals affected:**
- Signal B SLV: meaningless — single-word lines vs. long stanzas create extreme variance
- Signal B TTR: rare/archaic vocabulary inflates TTR above AI threshold
- Signal A coherence: intentional incoherence misread as human marker

**Direction:** AI-generated poetry → false negative; human poetry → unpredictable

**Mitigation:** Detect poem structure (line-break ratio) and return `INDETERMINATE_POETRY`

---

### Edge Case 2: Academic Papers Written by Humans

**Why detection fails:** Human academics are trained to write like AI: high formality, passive voice, consistent paragraph structure.

**Signals affected:**
- Signal A formality: human academic prose scores at AI-like ceiling
- Signal A coherence: structured arguments score as high as AI output
- Signal B SLV: academic writing deliberately maintains consistent sentence length

**Direction:** Strong false positive — most institutionally damaging failure mode

**Mitigation:** Domain classifier upstream; require higher threshold (0.85) for academic content

---

### Edge Case 3: ESL Writers

**Why detection fails:** ESL writers produce restricted vocabulary (low TTR) and short declarative sentences (low SLV) — both AI markers — due to language limitations, not AI generation.

**Signals affected:**
- Signal B TTR: constrained vocabulary → low TTR matches AI signature
- Signal B SLV: short declarative sentences → low variance matches AI signature

**Direction:** False positive — with serious equity implications (system structurally biased against non-native speakers)

**Mitigation:** Add grammatical error density as counter-signal (AI text is grammatically clean; ESL text has characteristic error patterns)

---

### Edge Case 4: Heavily Edited AI Content

**Why detection fails:** Even 30–40% human rewriting destroys the stylometric fingerprint. Adding contractions, varying rhythm, injecting anecdotes all push scores toward human range.

**Signals affected:** Both signals — all metrics drift toward human after editing

**Direction:** False negative — the core adversarial case

**Mitigation:** No stylometric approach fully defeats deliberate editing. Flag borderline 0.45–0.55 range for human review.

---

### Edge Case 5: Very Short Text (Under 100 Words)

**Why detection fails:** All stylometric features are statistical aggregates over a distribution of sentences. Fewer than 8–10 sentences produces near-zero degrees of freedom.

**Signals affected:**
- Signal B SLV: 3–5 sentences → single outlier sentence swings the metric completely
- Signal B TTR: length-dependent — short texts always have higher TTR regardless of authorship
- Signal A: LLM has insufficient context for reliable formality/coherence assessment

**Direction:** Unpredictable; false positive bias due to TTR inflation

**Mitigation:** Enforce 150-word minimum; return `INSUFFICIENT_TEXT` below threshold

---

### Additional Edge Case 6: Technical / Code-Mixed Text

**Why detection fails:** Code tokens inflate TTR to near-1.0, distort PD with syntax punctuation, and create extreme SLV.

**Mitigation:** Strip code blocks before stylometric computation; add code-density modifier

---

### Additional Edge Case 7: Templated / Form-Based Human Writing

**Why detection fails:** Legal contracts, HR policies — maximally formal, structurally uniform, low SLV, low TTR — all four metrics match AI profile simultaneously.

**Mitigation:** Structural template detector; `STRUCTURED_DOCUMENT` label with suppressed stylometric weight

---

### Summary Table

| Edge Case | Failing Signal(s) | Direction | Risk |
|---|---|---|---|
| Academic writing (human) | Both | FP | Critical |
| ESL writers | Signal B | FP | Critical (equity) |
| Poetry | Signal B | FN both directions | High |
| Heavily edited AI | Both | FN | High (adversarial) |
| Very short text | Signal B | FP bias | High |
| Technical/code-mixed | Signal B | FP | Medium-High |
| Templated documents | Both | FP | Medium |

---

## AI Tool Plan

### Tools Used in Planning Phase

| Tool | Usage |
|---|---|
| Claude (Anthropic) | Architecture design, requirements analysis, planning document drafting |
| Groq API (meta-llama/llama-4-scout-17b-16e-instruct) | Detection Signal 1 — runtime LLM classification |

### Milestone 3 — Submission Endpoint

**Prompt plan:**
- Prompt Claude to scaffold Flask app with `/submit` route, input validation, and UUID generation
- Prompt Claude to write `groq_signal.py` with system prompt, error fallback to 0.5, and JSON parsing
- Prompt Claude to write `audit/log.py` with thread-safe append-only list and JSONL persistence

**Verification plan:**
- Manually curl POST `/submit` with AI-like text; verify `content_id` returned
- Manually curl GET `/log`; verify entry appears with all required fields
- Kill server, restart; verify JSONL file reloads existing entries

---

### Milestone 4 — Detection Pipeline

**Prompt plan:**
- Prompt Claude to write `stylometric_signal.py` implementing SLV, TTR, PD with normalization
- Prompt Claude to write `engine/confidence.py` combining scores at 60/40 weights
- Prompt Claude to write `engine/labels.py` with explicit threshold constants

**Verification plan:**
- Submit clearly AI text; verify both signal scores are high, label = "Likely AI"
- Submit clearly human text; verify LLM score low, label = "Likely Human" or "Uncertain"
- Submit borderline text; verify score lands in 0.35–0.64 range, label = "Uncertain"

---

### Milestone 5 — Production Features

**Prompt plan:**
- Prompt Claude to implement POST `/appeal` with content_id lookup, status update, appeal event logging
- Prompt Claude to configure Flask-Limiter with 10/min and 100/day limits and custom 429 handler

**Verification plan:**
- Submit content, then appeal it; verify status changes to `under_review` in GET `/log`
- Fire 11 rapid requests to `/submit`; verify 11th returns HTTP 429

---

### What Will NOT Be AI-Generated

- System prompt content (human-authored based on deliberate analysis of AI writing patterns)
- Confidence thresholds (chosen based on reasoning about false positive harm, not AI suggestion)
- Label text (deliberately human-crafted for accessibility and plain language)
- Spec Reflection section of README (student's own analytical writing)

---

## Testing Results

All tests run against live server with Groq API key active (model: `meta-llama/llama-4-scout-17b-16e-instruct`).

---

### Test 1 — Clearly AI Text

**Input:** `"The mitochondria is the powerhouse of the cell. It is important to note that ATP synthesis is essential for cellular function. In conclusion, understanding cellular respiration is key to appreciating how organisms produce energy efficiently."`

**Result:**
```json
{
  "content_id": "facb5743-07bf-47f2-9273-9fd4434fa1ca",
  "attribution": "ai",
  "confidence": 0.8364,
  "label": "Likely AI",
  "signals": { "groq_llm": 0.9, "stylometric": 0.7411 },
  "status": "active"
}
```

**Analysis:** Both signals agree strongly. Groq flagged "It is important to note" and "In conclusion" as AI hedging phrases. Stylometric flagged low sentence length variance and low punctuation density. Combined 0.84 → "Likely AI" ✅

---

### Test 2 — Clearly Human Text

**Input:** `"ok so i finally figured out why my sourdough keeps dying lol. turns out i was feeding it too much flour and not enough water?? my friend told me this like three weeks ago and i totally ignored her. anyway its bubbling now so fingers crossed"`

**Result:**
```json
{
  "content_id": "2bacaee9-89fb-498c-9bf4-9585e9c695a2",
  "attribution": "uncertain",
  "confidence": 0.3841,
  "label": "Uncertain",
  "signals": { "groq_llm": 0.1, "stylometric": 0.8102 },
  "status": "active"
}
```

**Analysis:** LLM correctly scored 0.10 (informal register, personal narrative, colloquialisms). Stylometric scored 0.81 — false positive from high type-token ratio caused by casual/varied informal vocabulary. This is the ESL/informal-writing edge case: stylometric TTR metric penalizes high vocabulary variety even when it is human-natural. Combined score 0.38 landed in "Uncertain" rather than "Likely Human". Demonstrates why the wide Uncertain band exists.

---

### Test 3 — Appeal Submission

**Input:** content_id `2bacaee9-89fb-498c-9bf4-9585e9c695a2`, reasoning: `"I wrote this myself. The informal style reflects my personal voice, not AI generation."`

**Result:**
```json
{
  "content_id": "2bacaee9-89fb-498c-9bf4-9585e9c695a2",
  "status": "appeal_received",
  "previous_label": "Uncertain",
  "message": "Your appeal has been logged. The content is now marked as under_review."
}
```

**Analysis:** Appeal accepted. Status updated to `under_review`. Original decision preserved. `creator_reasoning` stored in audit log. 

---

### Test 4 — GET /log (excerpt)

Audit log confirmed 8 entries after all tests. Key entries:

| content_id (short) | creator_id | label | llm | stylo | confidence | status |
|---|---|---|---|---|---|---|
| facb5743 | test_ai | Likely AI | 0.90 | 0.74 | 0.84 | active |
| 2bacaee9 | test_human | Uncertain | 0.10 | 0.81 | 0.38 | under_review |

Appeal event entry also present in log with `event_type: "appeal_submitted"` and full `creator_reasoning`. 
