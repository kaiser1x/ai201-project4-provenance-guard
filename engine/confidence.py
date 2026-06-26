def combine_scores(
    groq_score: float,
    stylo_score: float,
    w_groq: float = 0.60,
    w_stylo: float = 0.40,
) -> float:
    combined = (w_groq * groq_score) + (w_stylo * stylo_score)
    return round(max(0.0, min(1.0, combined)), 4)
