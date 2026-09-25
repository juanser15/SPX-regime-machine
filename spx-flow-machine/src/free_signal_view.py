"""Presentation-only labels for the persisted FREE daily signal."""

from datetime import datetime, timezone
import math


def pm_action(risk_signal: object) -> str:
    """Do not turn a neutral or unknown research signal into a trade."""
    return {
        "RISK-ON": "RISK-ON",
        "NEUTRAL": "HOLD / NO ACTION",
        "DE-RISK": "DE-RISK",
    }.get(str(risk_signal), "HOLD / NO ACTION")


def tail_hedge_status(tail_score: object) -> str:
    """Display-only use of the existing 35/65 stress bands, not a hedge model."""
    try:
        score = float(tail_score)
    except (TypeError, ValueError):
        return "UNAVAILABLE"
    if not math.isfinite(score):
        return "UNAVAILABLE"
    if score <= 35:
        return "OFF"
    if score < 65:
        return "WATCH"
    return "ACTIVE"


def short_drivers(raw: object) -> list[str]:
    """Keep at most three existing model drivers; never synthesize new ones."""
    return [part.strip() for part in str(raw or "").split(";") if part.strip()][:3]


def session_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]


def retrieved_timestamp(value: object) -> str:
    if not value:
        return "Unavailable"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
            timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return str(value)


def score_label(value: object) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "Unavailable"
    return f"{score:.1f}/100" if math.isfinite(score) else "Unavailable"