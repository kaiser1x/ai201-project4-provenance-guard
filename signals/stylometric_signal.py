import math
import re


def stylometric_score(text: str) -> float:
    """Return 0.0–1.0 AI likelihood via stylometric analysis. Pure Python, no external API."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    words = re.findall(r"[a-zA-Z']+", text.lower())

    if len(sentences) < 2 or len(words) < 10:
        return 0.5

    # Sentence Length Variance — low variance = AI-like
    sent_lengths = [len(re.findall(r"[a-zA-Z']+", s)) for s in sentences]
    mean_len = sum(sent_lengths) / len(sent_lengths)
    variance = sum((l - mean_len) ** 2 for l in sent_lengths) / len(sent_lengths)
    std_dev = math.sqrt(variance)
    slv_score = 1.0 / (1.0 + math.exp(std_dev - 4.0))

    # Type-Token Ratio — excess above 0.65 = AI-like
    ttr = len(set(words)) / len(words)
    ttr_score = min(1.0, max(0.0, ttr - 0.65) / 0.20)

    # Punctuation Density — shortfall below 0.04 = AI-like
    punct_count = sum(1 for c in text if not c.isalnum() and c != ' ')
    pd = punct_count / max(1, len(text))
    pd_score = min(1.0, max(0.0, 0.04 - pd) / 0.04)

    combined = (0.50 * slv_score) + (0.30 * ttr_score) + (0.20 * pd_score)
    return round(max(0.0, min(1.0, combined)), 4)
