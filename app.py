import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit.log import AuditLog
from engine.confidence import combine_scores
from engine.labels import assign_label, assign_attribution
from signals.groq_signal import groq_llm_score
from signals.stylometric_signal import stylometric_score

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per day", "10 per minute"],
    storage_uri="memory://",
)

audit_log = AuditLog()


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "error": "rate_limited",
        "message": "Too many requests. Please wait before submitting again.",
    }), 429


@app.post("/submit")
@limiter.limit("10 per minute")
@limiter.limit("100 per day")
def submit():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "missing_fields", "message": "Request body must be JSON"}), 400

    text = data.get("text", "").strip()
    creator_id = data.get("creator_id", "").strip()

    if not text:
        return jsonify({"error": "invalid_input", "message": "text is required and must not be empty"}), 400
    if not creator_id:
        return jsonify({"error": "missing_fields", "message": "creator_id is required"}), 400
    if len(text) < 20:
        return jsonify({"error": "invalid_input", "message": "text must be at least 20 characters"}), 400
    if len(text) > 10000:
        return jsonify({"error": "invalid_input", "message": "text must not exceed 10,000 characters"}), 400

    llm_score = groq_llm_score(text)
    stylo_score = stylometric_score(text)
    confidence = combine_scores(llm_score, stylo_score)
    label = assign_label(confidence)
    attribution = assign_attribution(confidence)
    content_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
        "llm_score": llm_score,
        "stylometric_score": stylo_score,
        "status": "active",
        "timestamp": timestamp,
        "text_preview": text[:100],
    }
    audit_log.append(entry)

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
        "signals": {
            "groq_llm": llm_score,
            "stylometric": stylo_score,
        },
        "status": "active",
        "timestamp": timestamp,
    }), 200


@app.post("/appeal")
@limiter.limit("10 per minute")
@limiter.limit("100 per day")
def appeal():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "missing_fields", "message": "Request body must be JSON"}), 400

    content_id = data.get("content_id", "").strip()
    creator_reasoning = data.get("creator_reasoning", "").strip()

    if not content_id:
        return jsonify({"error": "missing_fields", "message": "content_id is required"}), 400
    if not creator_reasoning:
        return jsonify({"error": "missing_fields", "message": "creator_reasoning is required"}), 400

    original = audit_log.get_by_id(content_id)
    if original is None:
        return jsonify({"error": "content_not_found", "message": f"No submission found with content_id {content_id}"}), 404

    if original.get("status") == "under_review":
        return jsonify({"error": "appeal_already_open", "message": "An appeal is already open for this content"}), 409

    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    previous_label = original.get("label")

    audit_log.update_status(content_id, "under_review")

    appeal_entry = {
        **original,
        "status": "under_review",
        "event_type": "appeal_submitted",
        "creator_reasoning": creator_reasoning,
        "appeal_timestamp": timestamp,
    }
    audit_log.append(appeal_entry)

    return jsonify({
        "status": "appeal_received",
        "content_id": content_id,
        "previous_label": previous_label,
        "message": "Your appeal has been logged. The content is now marked as under_review.",
    }), 200


@app.get("/log")
def get_log():
    creator_id_filter = request.args.get("creator_id")
    entries = audit_log.get_all()

    if creator_id_filter:
        entries = [e for e in entries if e.get("creator_id") == creator_id_filter]

    return jsonify({"count": len(entries), "entries": entries}), 200


if __name__ == "__main__":
    app.run(debug=True)
