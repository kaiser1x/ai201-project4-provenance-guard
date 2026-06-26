# Provenance Guard
## AI201 · Project 4 — Content Attribution System

---

## Project Overview

Provenance Guard is a Flask API that analyzes text content and returns a transparency label indicating whether the content was likely written by a human, an AI tool, or is of uncertain origin. The system combines two independent detection signals — an LLM-based semantic classifier and a local stylometric analyzer — into a single confidence score, then maps that score to a human-readable label.

Content attribution matters because AI-generated text is now indistinguishable from human writing at a surface level, creating real risks in academic, journalistic, and professional contexts. A student submitting AI work as their own, a journalist publishing unverified AI content, or a platform hosting AI-spam all benefit from automated provenance signals. Provenance Guard does not make final decisions — it provides structured evidence that helps human reviewers act faster and more consistently.

---

## Architecture Overview

```
[Client Request]
      |
      v
[Rate Limiter]  ←── 10/min, 100/day per IP ──→ 429
      |
      v
[Input Validator]  ──→ 400 if missing/invalid
      |
      v
+----------------------------------+
|       Detection Pipeline         |
|                                  |
|  [Groq LLM Signal]  (60% weight) |
|         +                        |
|  [Stylometric Signal] (40%)      |
|         |                        |
|  [Confidence Engine]             |
|         |                        |
|  [Label Generator]               |
+----------------------------------+
      |
      v
[Audit Logger] ──→ audit_log.jsonl
      |
      v
[JSON Response → Client]
```

**Components:**
- **Flask Application** (`app.py`) — routing, rate limiting, error handling
- **Groq LLM Signal** — calls Groq API; returns 0.0–1.0 AI likelihood
- **Stylometric Signal** — pure Python; sentence length variance, type-token ratio, punctuation density
- **Confidence Engine** — weighted average (60% Groq / 40% stylometric)
- **Label Generator** — maps score to three-state label
- **Audit Log** — append-only in-memory list + optional JSONL file

---

## Setup / Installation

```bash
# Clone and enter the project
cd ai201-project4-provenance-guard

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -r requirements.txt
```

---

## Environment Variables

Create a `.env` file in the project root (never commit this file):

```
GROQ_API_KEY=your_groq_api_key_here
```

Get a free Groq API key at console.groq.com.

---

## Running the Server

```bash
flask run
# or
python app.py
```

Server runs at `http://localhost:5000` by default.

---

## API Reference

### POST /submit

Analyze text and return an attribution label.

**Request:**
```bash
curl -X POST http://localhost:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "Your text here (minimum 20 characters)", "creator_id": "user123"}'
```

**Response (200):**
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

**Error responses:** 400 (missing/invalid fields), 429 (rate limited), 500 (Groq failure)

---

### POST /appeal

Dispute an attribution decision.

**Request:**
```bash
curl -X POST http://localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "550e8400-e29b-41d4-a716-446655440000", "creator_reasoning": "I wrote this myself."}'
```

**Response (200):**
```json
{
  "status": "appeal_received",
  "content_id": "550e8400-e29b-41d4-a716-446655440000",
  "previous_label": "Likely AI",
  "message": "Your appeal has been logged. The content is now marked as under_review."
}
```

**Error responses:** 400 (missing fields), 404 (content_id not found), 429 (rate limited)

---

### GET /log

Retrieve the full audit history.

**Request:**
```bash
curl http://localhost:5000/log
# Filter by creator:
curl "http://localhost:5000/log?creator_id=user123"
```

**Response (200):**
```json
{
  "count": 3,
  "entries": [
    {
      "content_id": "uuid",
      "creator_id": "user123",
      "attribution": "ai",
      "confidence": 0.85,
      "label": "Likely AI",
      "status": "active",
      "timestamp": "2026-06-23T14:32:01Z"
    }
  ]
}
```

---

## Detection Signals

Provenance Guard uses two independent signals to reduce false positives that would occur with a single approach.

### Signal 1 — Groq LLM Classification (60% weight)

The system sends submitted text to a Groq-hosted language model (llama3-8b-8192) and asks it to evaluate four dimensions:

1. **Semantic coherence** — AI text has unnaturally smooth, uniform transitions between sentences
2. **AI writing characteristics** — hedging phrases like "It is important to note," "In conclusion," perfectly balanced paragraph lengths
3. **Formality register** — AI text maintains an artificially consistent register with no colloquialisms or register shifts
4. **Repetition patterns** — AI text reuses the same sentence-opening patterns and transitional phrases

The model returns a score from 0.0 (almost certainly human) to 1.0 (almost certainly AI). If the Groq API is unavailable, the signal defaults to 0.5 (neutral) so the system continues operating.

**Analogy:** Think of this like asking an experienced editor whether the writing "feels" like AI — they recognize the patterns even without measuring them explicitly.

**Weakness:** Formal academic writing looks identical to AI writing on these dimensions. A professor's paper may score high on this signal.

---

### Signal 2 — Stylometric Analysis (40% weight)

A pure-Python algorithm (no external API) measures three statistical properties of the text:

1. **Sentence Length Variance** — AI text uses uniformly medium-length sentences. Human writing varies between short punchy sentences and long complex ones. Low variance = higher AI score.

2. **Type-Token Ratio (vocabulary richness)** — AI text often has an artificially high and consistent vocabulary variety. Very high TTR = higher AI score.

3. **Punctuation Density** — Human writing uses dashes, ellipses, colons, and semicolons more naturally. AI text tends to avoid complex punctuation. Low punctuation density = higher AI score.

**Analogy:** Think of this like measuring a writer's fingerprint — not what they say, but the mathematical patterns in how they write.

**Weakness:** A human who edits AI output (adding contractions, varying sentence rhythm) can defeat all three metrics.

---

## Confidence Scoring

The two signal scores are combined into a single confidence value using a weighted average: 60% Groq signal + 40% stylometric signal.

| Score Range | Label | What It Means |
|---|---|---|
| 0.00 – 0.34 | **Likely Human** | Both signals lean strongly human |
| 0.35 – 0.64 | **Uncertain** | Signals disagree or neither is strong |
| 0.65 – 1.00 | **Likely AI** | Both signals lean strongly AI |

**Why these thresholds?** The "Uncertain" band is intentionally wide (30 points) to reduce false positives. Falsely labeling a human creator's work as AI-generated is more damaging than missing an AI submission — so the system requires strong evidence before assigning an AI label.

---

## Transparency Labels

Every analyzed piece of content receives one of three labels.

### AI-Generated

> **This content shows strong signs of being written by an AI tool rather than a person. You may want to verify key facts with an additional source before relying on it.**

Assigned when confidence score ≥ 0.65. Treat with extra care; check facts; do not cite as human-authored.

---

### Human-Written

> **This content shows strong signs of being written by a person. It may still contain errors or bias, so normal critical reading still applies.**

Assigned when confidence score ≤ 0.34. No special action required.

---

### Origin Unclear

> **This content could have been written by a person, an AI tool, or a combination of both. A human reviewer should check it before it is used in contexts where authorship matters.**

Assigned when confidence score is 0.35–0.64. Do not rely on this content in authorship-sensitive contexts without human review.

---

### Why Plain Language?

Labels use hedged, plain-language phrasing on purpose. AI detection is probabilistic — no system is 100% accurate. "Likely AI-Generated" is more honest than "AI-Generated" and more accessible than a numeric score. Every reader, regardless of technical background, should understand what the label means and what to do about it.

---

## Rate Limiting

Provenance Guard limits how often any single IP address can submit content for analysis.

| Window | Limit |
|---|---|
| Per minute | 10 requests |
| Per day | 100 requests |

### Why these limits?

Every submission calls the Groq AI service, which charges per request. Without limits, a single automated script could generate thousands of charges in seconds, making the service unsustainable.

The 10/minute limit is about five times the pace of a human manually submitting content — normal users will never encounter it. The 100/day limit is generous for even heavy creators (who typically publish 5–30 pieces/day).

### What happens if you hit the limit?

You'll receive HTTP 429 with:
```json
{
  "error": "rate_limited",
  "message": "Too many requests. Please wait before submitting again.",
  "retry_after_seconds": 47
}
```

Wait the indicated number of seconds and try again. There is no penalty — your quota resets automatically (minute limits reset each minute; day limits reset at midnight UTC).

---

## Audit Log Examples

### Example 1 — High-Confidence AI Detection

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

Both signals agree at near-ceiling values. The text uses "It is important to note," has uniform sentence length, and avoids complex punctuation — all strong AI markers.

---

### Example 2 — High-Confidence Human Detection

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

Informal register, personal narrative, intentional grammatical looseness, and idiosyncratic punctuation all push both signals toward human.

---

### Example 3 — Appeal Event

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

The creator disputed the AI label. The original decision is preserved; only the status changes to `under_review`. The `creator_reasoning` is stored in the log for reviewer context.

---

## Appeals Workflow

If Provenance Guard labels your content incorrectly, you can file an appeal.

### How to Submit an Appeal

```bash
curl -X POST http://localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "the-uuid-from-your-submit-response",
    "creator_reasoning": "Explain why you believe the label is incorrect."
  }'
```

### What Happens Next

1. The system looks up your original submission by `content_id`
2. Your `creator_reasoning` is saved to the audit log
3. The submission status changes from `active` to `under_review`
4. Your original label and scores are preserved (not overwritten)
5. A human reviewer can examine the full audit trail and make a final determination

### Appeal States

```
active → under_review → resolved (upheld or overturned)
```

Appeals cannot be submitted for submissions that are already `resolved`. Only one open appeal is allowed per submission at a time.

---

## Known Limitations

1. **Academic and formal human writing** triggers false positives because the stylistic markers the system uses to identify AI (consistent register, high formality, smooth transitions) are the same markers trained writers use intentionally. A professor's research paper may be flagged as AI-generated.

2. **ESL (English as Second Language) writers** are structurally disadvantaged. Restricted vocabulary produces low type-token ratios, and short declarative sentences produce low sentence length variance — both AI markers. The system is biased against non-native speakers.

3. **Very short text (under ~150 words)** produces unreliable scores. Stylometric features are statistical aggregates over sentence distributions; with fewer than 8–10 sentences, the metrics become noise. Scores for short texts should not be acted upon.

4. **Heavily edited AI content** cannot be reliably detected. If a human rewrites 30–40% of AI-generated text — varying rhythm, adding personal anecdotes, introducing contractions — all three stylometric features shift into the human range. The system cannot identify this hybrid authorship.

5. **Poetry and creative prose** defeats stylometric analysis completely. Extreme sentence length variation, unusual punctuation, and deliberate deviation from prose norms make all three metrics meaningless. Do not use Provenance Guard for poetic content.

6. **Technical or code-mixed text** inflates type-token ratio (code identifiers are unique tokens) and distorts punctuation density (syntax characters are counted). Human-written technical documentation with code blocks may score as AI-generated.

7. **Future AI models** — detection signals were calibrated against current LLM output patterns. As AI writing improves and evolves, the signals will need recalibration. A model trained in 2028 may produce text with very different stylometric properties.

---

## Spec Reflection

Designing Provenance Guard required making explicit choices about where to locate risk in a classification system with no perfect answers. The most consequential decision was choosing a wide "Uncertain" band (0.35–0.64) rather than a narrow one. A narrower uncertain band would produce more definitive labels, which feels more useful — but definitive wrong labels are more damaging than honest uncertainty. In content moderation, falsely accusing a human creator of using AI has asymmetric consequences: it damages reputation, discourages legitimate creators, and erodes trust in the system. The design deliberately accepts more "Uncertain" verdicts in exchange for higher precision on the labels it does commit to.

The decision to use two independent signals rather than one (or three) reflects a specific theory about error types. A single LLM classifier, however sophisticated, has a blind spot: it shares the same stylistic training distribution as the AI text it's trying to detect. Adding a purely statistical stylometric signal — one that doesn't "understand" language at all, but only measures surface patterns — provides a genuinely different kind of evidence. The two signals fail in different scenarios (the LLM struggles with formal human writing; the stylometric signal struggles with edited AI text), so disagreement between them is itself informative. Three signals would add marginal coverage at the cost of interpretability and increased latency.

With more time, several improvements would meaningfully change the system's accuracy. First, the stylometric thresholds were set based on general intuition about human vs. AI writing, not empirical calibration against a labeled dataset — measuring actual false positive rates on academic writing, ESL writing, and legal documents would almost certainly require adjusting both the feature weights and the label thresholds. Second, the Groq signal falls back to 0.5 on API failure, but a smarter fallback would cache recent Groq scores for similar texts rather than returning a neutral score that buries the stylometric signal. Third, an honest v2 would add a minimum-length gate (returning `INSUFFICIENT_TEXT` rather than a label for short texts) and a content-type detector that suppresses stylometric analysis for poetry and code.

---

## AI Usage

**Claude (Anthropic):** Used throughout planning and development. Claude assisted with architecture design, detection signal research, system prompt engineering for the Groq classifier, audit log schema design, and planning document drafting. The multi-agent planning structure (11 parallel agents covering different aspects of the system) was orchestrated through Claude Code.

**Groq API (llama3-8b-8192):** Used as Signal 1 at runtime. The model receives submitted text and returns an AI-likelihood score based on a hand-crafted system prompt. The system prompt itself was designed by the student based on analysis of known AI writing characteristics, then refined through testing.

**What was NOT AI-generated:**
- The confidence threshold values (0.35 and 0.65) — chosen based on explicit reasoning about false positive harm
- The transparency label text — deliberately written for plain-language accessibility
- The Spec Reflection section — student's own analytical writing
- The system prompt for the Groq classifier — authored by the student, not generated

**Reflection:** AI assistance significantly accelerated the planning phase, particularly for enumerating edge cases and formalizing the audit log schema. The most valuable use was parallel generation of architecture, signal design, and API contract simultaneously, which revealed contradictions early (e.g., different agents proposed different threshold values, forcing an explicit decision). The risk was over-relying on AI-generated structure without stress-testing assumptions — the edge case analysis revealed that the ESL false positive problem is more serious than any single planning document suggested.

---

## Walkthrough Video

[Walkthrough Video — link to be added before submission]

The video demonstrates a live submission with human-authored text, a live submission with AI-authored text, the differing confidence scores and labels, an appeal submission, and the GET /log audit history.
