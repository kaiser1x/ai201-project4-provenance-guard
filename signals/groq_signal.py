import json
import os

SYSTEM_PROMPT = """You are an AI writing detector. Your sole task is to analyze text and output a \
single JSON object — nothing else.

Evaluate the text across these four dimensions:

1. Semantic coherence: Does every sentence logically connect to the next with no \
abrupt topic jumps? AI text tends toward uniform, over-smooth transitions.

2. AI writing characteristics: Look for hedging phrases ("it is important to \
note", "in conclusion", "it is worth mentioning"), bullet-point sentence \
structures embedded in prose, and unnaturally balanced paragraph lengths.

3. Formality register: Is the register artificially consistent throughout, with \
no colloquialisms, contractions, or register shifts? Human writing shows \
natural register variation.

4. Repetition patterns: Are the same sentence-opening patterns, conjunctions, or \
transitional phrases reused at a rate higher than natural human writing?

Return ONLY this JSON (no surrounding text, no explanation):
{"ai_score": <float between 0.0 and 1.0>}

Where 0.0 means almost certainly human-written and 1.0 means almost certainly AI-generated."""

USER_PROMPT = """Analyze the following text and return your JSON score:

---
{text}
---"""


def groq_llm_score(text: str) -> float:
    """Return 0.0–1.0 AI likelihood via Groq LLM. Falls back to 0.5 on any failure."""
    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT.format(text=text)},
            ],
            temperature=0.0,
            max_tokens=32,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
        return max(0.0, min(1.0, float(data["ai_score"])))
    except Exception as e:
        print(f"[groq_signal error] {e}")
        return 0.5
