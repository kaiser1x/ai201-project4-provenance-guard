# AI201 Project 4: Provenance Guard — Requirements Checklist

---

## 1. Planning Document (`planning.md`)

- [ ] `planning.md` exists at the repo root before any code is written
- [ ] Describes the overall system architecture (how components interact)
- [ ] Explains the two detection signals and how they will be combined
- [ ] Describes the confidence scoring logic (how 0.0–1.0 is derived)
- [ ] Describes the label assignment logic ("Likely Human" / "Uncertain" / "Likely AI")
- [ ] Describes the audit log schema (fields and types)
- [ ] Describes the appeal workflow (what changes, what persists)
- [ ] Lists all API endpoints with expected inputs and outputs
- [ ] ⚠️ Written in future tense / planning voice — must predate code commits (graders check git history)

---

## 2. Flask API — Core Endpoints (source code)

### POST `/submit`
- [ ] Endpoint accepts `text` field in request body
- [ ] Endpoint accepts `creator_id` field in request body
- [ ] Returns `attribution_label` in response (one of the three valid labels)
- [ ] Returns `confidence_score` (float, 0.0–1.0) in response
- [ ] Returns a unique `content_id` that can be referenced later
- [ ] Returns HTTP 200 on success
- [ ] ⚠️ Returns appropriate HTTP error codes (400) for missing/invalid fields
- [ ] ⚠️ Input validated — empty `text` or missing `creator_id` rejected gracefully

### POST `/appeal`
- [ ] Endpoint accepts `content_id` field in request body
- [ ] Endpoint accepts `creator_reasoning` field in request body
- [ ] Looks up the original submission by `content_id`
- [ ] Updates the submission's status to reflect appeal received
- [ ] Returns confirmation of appeal with updated record
- [ ] ⚠️ Returns 404 (or equivalent) if `content_id` does not exist
- [ ] ⚠️ `creator_reasoning` is stored and visible in the audit log

### GET `/log`
- [ ] Returns the full audit history as a list/array
- [ ] Each log entry contains `content_id`
- [ ] Each log entry contains `creator_id`
- [ ] Each log entry contains `text` (or a reference to it)
- [ ] Each log entry contains `attribution_label`
- [ ] Each log entry contains `confidence_score`
- [ ] Each log entry contains timestamp of submission
- [ ] Each log entry reflects appeal status / `creator_reasoning` if an appeal was filed
- [ ] ⚠️ Log is returned in a structured, machine-readable format (JSON array)

---

## 3. Detection Signals (source code)

### Signal 1 — Groq LLM Classification
- [ ] Groq API is called with the submitted `text`
- [ ] Groq response is parsed to extract a classification signal
- [ ] Groq API key is loaded from environment variable (not hard-coded)
- [ ] ⚠️ Errors from Groq API (timeout, quota) are handled and do not crash the server

### Signal 2 — Stylometric Analysis
- [ ] A local, rule-based or statistical stylometric analysis is implemented (no external API required)
- [ ] Analysis examines at least one stylometric feature (e.g., average sentence length, vocabulary richness, punctuation patterns, function-word frequency)
- [ ] Analysis produces a numeric signal that contributes to the final score
- [ ] ⚠️ Stylometric analysis runs independently of Groq (so the system degrades gracefully if Groq is unavailable)

### Confidence Scoring
- [ ] Both signals are combined into a single `confidence_score` between 0.0 and 1.0
- [ ] Combination logic is deterministic and documented
- [ ] Score of 0.0 represents maximum certainty of human authorship
- [ ] Score of 1.0 represents maximum certainty of AI authorship
- [ ] ⚠️ Intermediate range is mapped consistently to the "Uncertain" label

### Label Assignment
- [ ] "Likely Human" label assigned when confidence_score is in the low range
- [ ] "Uncertain" label assigned when confidence_score is in the middle range
- [ ] "Likely AI" label assigned when confidence_score is in the high range
- [ ] Thresholds are explicitly defined in code (not magic numbers scattered inline)
- [ ] ⚠️ All three labels are reachable by the logic (no dead label state)

---

## 4. Rate Limiting (source code)

- [ ] Flask-Limiter is installed and configured
- [ ] `/submit` endpoint is limited to **10 requests per minute** per client
- [ ] `/submit` endpoint is limited to **100 requests per day** per client
- [ ] ⚠️ Rate limit exceeded returns HTTP 429 with an informative message
- [ ] ⚠️ `/appeal` and `/log` endpoints have rate limits applied (implicit expectation — verify in rubric)
- [ ] ⚠️ Rate limit key is based on a meaningful identifier (IP or `creator_id`), not a global counter

---

## 5. Audit Log (source code)

- [ ] Audit log persists across requests (in-memory dict/list at minimum, or file/DB)
- [ ] Every `/submit` call creates a new log entry
- [ ] Every `/appeal` call updates the existing log entry (does not create a duplicate)
- [ ] Log entries include all structured fields listed in the `/log` section above
- [ ] ⚠️ Log is append-only for submissions (original label/score are never silently overwritten by an appeal)

---

## 6. README.md

- [ ] `README.md` exists at the repo root
- [ ] **Project overview** section: describes what Provenance Guard does
- [ ] **Setup / Installation** section: how to install dependencies (`pip install`, `requirements.txt`, etc.)
- [ ] **Environment variables** section: lists all required env vars (e.g., `GROQ_API_KEY`)
- [ ] **Running the server** section: exact command to start the Flask app
- [ ] **API reference** section: documents all three endpoints (method, path, request body, response body)
- [ ] **Detection methodology** section: explains the two signals and how confidence is computed
- [ ] **Rate limiting** section: states the limits and which endpoints they apply to
- [ ] ⚠️ Includes example `curl` commands or sample request/response JSON for each endpoint
- [ ] ⚠️ Mentions any known limitations or assumptions

---

## 7. Portfolio Walkthrough Video

- [ ] Video is recorded and linked (or submitted) per course instructions
- [ ] Demonstrates a successful POST `/submit` call with a human-authored text sample
- [ ] Demonstrates a successful POST `/submit` call with an AI-authored text sample
- [ ] Shows the differing `confidence_score` and `label` between the two samples
- [ ] Demonstrates POST `/appeal` updating a submission
- [ ] Demonstrates GET `/log` returning the audit history with both entries
- [ ] Verbally or visually explains the two detection signals
- [ ] Verbally explains the confidence scoring / label threshold logic
- [ ] ⚠️ Video is under the course time limit (check syllabus — typically 3–5 min)
- [ ] ⚠️ Code is visible during the walkthrough (screen share of editor or terminal)

---

## 8. Code Quality & Repository Hygiene ⚠️ (implicit grading)

- [ ] `requirements.txt` (or `pyproject.toml`) is present and complete
- [ ] `.env` / secrets are **not** committed to the repo (`.gitignore` covers them)
- [ ] Flask app is structured with clear separation of concerns (routes, detection logic, audit log)
- [ ] No hard-coded API keys or passwords anywhere in the source
- [ ] Code runs without errors from a clean `pip install -r requirements.txt` + `flask run`
- [ ] ⚠️ `planning.md` commit timestamp predates first code commit (graders may inspect git log)
- [ ] ⚠️ All three label states are exercised by at least one manual test shown in the video

---

## Quick-Reference: Deliverable Map

| Requirement Area | Deliverable |
|---|---|
| Architecture & design decisions | `planning.md` |
| API endpoints (submit / appeal / log) | Source code |
| Groq LLM signal | Source code |
| Stylometric signal | Source code |
| Confidence scoring & label logic | Source code |
| Rate limiting | Source code |
| Audit log persistence | Source code |
| Setup, env vars, API docs, examples | `README.md` |
| Live demo of all endpoints + signals | Video |
| Repo hygiene, no secrets, requirements | Source code / repo |
