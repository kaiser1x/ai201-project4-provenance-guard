HUMAN_THRESHOLD = 0.35
AI_THRESHOLD = 0.65


def assign_label(score: float) -> str:
    if score < HUMAN_THRESHOLD:
        return "Likely Human"
    elif score < AI_THRESHOLD:
        return "Uncertain"
    else:
        return "Likely AI"


def assign_attribution(score: float) -> str:
    if score < HUMAN_THRESHOLD:
        return "human"
    elif score < AI_THRESHOLD:
        return "uncertain"
    else:
        return "ai"
