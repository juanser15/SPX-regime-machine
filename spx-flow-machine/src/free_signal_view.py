"""Read a verified Yahoo snapshot and format it for the FREE signal-only view."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from src.yahoo_daily_adapter import CANONICAL_COLUMNS, SERIES

INPUT_NAMES = {definition.canonical_field: definition.ticker for definition in SERIES}
NO_TAIL = "NOT AVAILABLE / INSUFFICIENT REAL DATA"
FRESHNESS_LIMIT = timedelta(hours=72)


@dataclass
class RealSignalBundle:
    latest: dict
    history: pd.DataFrame
    canonical: pd.DataFrame
    input_row: pd.Series
    missing_inputs: list[str]
    source: str


def load_verified_real_signal(output_dir: Path) -> RealSignalBundle:
    """Fail closed if the signal cannot be tied to its immutable real input snapshot."""
    root_manifest = json.loads((output_dir / "signal_manifest.json").read_text())
    signal_id = root_manifest["signal_snapshot_id"]
    signal_dir = output_dir / "snapshots" / signal_id
    manifest = json.loads((signal_dir / "signal_manifest.json").read_text())
    if signal_id != manifest["signal_snapshot_id"]:
        raise ValueError("Signal snapshot identity does not match its manifest.")
    history_bytes = (signal_dir / "signal_history.csv").read_bytes()
    if hashlib.sha256(history_bytes).hexdigest() != manifest["signal_history_sha256"]:
        raise ValueError("Signal history checksum does not match its manifest.")
    latest = json.loads((signal_dir / "latest_signal.json").read_text())
    history = pd.read_csv(signal_dir / "signal_history.csv", parse_dates=["date"])
    if history.empty or session_date(history.iloc[-1]["date"]) != latest["date"]:
        raise ValueError("Latest signal does not match signal history.")
    if str(history.iloc[-1]["risk_signal"]) != latest.get("risk_signal"):
        raise ValueError("Latest action does not match signal history.")

    input_id = manifest["input_data_snapshot_id"]
    if latest.get("data_snapshot_id") != input_id:
        raise ValueError("Latest signal does not match its input snapshot.")
    input_dir = output_dir / "daily_data" / "snapshots" / input_id
    data_manifest = json.loads((input_dir / "metadata_manifest.json").read_text())
    if (data_manifest.get("source") != "Yahoo Finance"
            or data_manifest.get("snapshot", {}).get("snapshot_id") != input_id
            or "Yahoo Finance" not in manifest.get("input_source", "")):
        raise ValueError("The signal is not linked to a verified Yahoo Finance snapshot.")
    if latest.get("retrieved_at_utc") != data_manifest.get("retrieved_at_utc"):
        raise ValueError("Signal retrieval time does not match its real inputs.")
    canonical_bytes = (input_dir / "canonical_daily.csv").read_bytes()
    if hashlib.sha256(canonical_bytes).hexdigest() != data_manifest["canonical_sha256"]:
        raise ValueError("Real input checksum does not match its manifest.")
    canonical = pd.read_csv(input_dir / "canonical_daily.csv")
    rows = canonical.loc[canonical["date"] == latest["date"]]
    if len(rows) != 1:
        raise ValueError("The signal's session has no unique observed input row.")
    input_row = rows.iloc[0]
    missing = [name for name in CANONICAL_COLUMNS[1:] if pd.isna(input_row[name])]
    return RealSignalBundle(
        latest=latest, history=history, canonical=canonical, input_row=input_row,
        missing_inputs=missing, source=data_manifest["source"],
    )


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
        return NO_TAIL
    if not math.isfinite(score):
        return NO_TAIL
    if score <= 35:
        return "OFF"
    if score < 65:
        return "WATCH"
    return "ACTIVE"


def short_drivers(raw: object) -> list[str]:
    """Keep at most three existing model drivers; never synthesize new ones."""
    return [part.strip() for part in str(raw or "").split(";") if part.strip()][:3]


def observed_drivers(raw: object, row: pd.Series) -> list[str]:
    """Show only existing drivers whose required inputs were observed on this date."""
    required = {
        "weak_20d_trend": ("spx_close",),
        "drawdown": ("spx_close",),
        "realized_volatility": ("spx_close",),
        "vix_level": ("vix_close",),
        "vix_acceleration": ("vix_close",),
        "skew": ("skew_close",),
        "vvix": ("vvix_close",),
        "front_vol_inversion": ("vix9d_close", "vix_close"),
        "vix_curve_inversion": ("vix_close", "vix3m_close"),
    }
    drivers = []
    for driver in short_drivers(raw):
        fields = required.get(driver.split("=", 1)[0])
        if fields and all(pd.notna(row.get(field)) for field in fields):
            drivers.append(driver)
    return drivers


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


def has_real_tail_inputs(row: pd.Series) -> bool:
    return bool(
        pd.notna(row.get("skew_close"))
        or pd.notna(row.get("vvix_close"))
        or (pd.notna(row.get("vix9d_close")) and pd.notna(row.get("vix_close")))
        or (pd.notna(row.get("vix_close")) and pd.notna(row.get("vix3m_close")))
    )


def decision_for_display(
    signal: dict, input_row: pd.Series, now: datetime | None = None
) -> tuple[str, bool, str | None]:
    """Presentation gate only: never present incomplete/stale research as today's action."""
    now = now or datetime.now(timezone.utc)
    retrieved = datetime.fromisoformat(
        str(signal["retrieved_at_utc"]).replace("Z", "+00:00")
    )
    if retrieved.tzinfo is None:
        raise ValueError("Real input retrieval time has no timezone.")
    session = datetime.fromisoformat(session_date(signal["date"])).date()
    available_at = datetime.combine(session, time(16), ZoneInfo("America/New_York"))
    available_at += timedelta(hours=6)
    if now < available_at:
        return "HOLD / NO ACTION", False, "The daily session is not yet eligible as a completed signal."
    if retrieved > now or now - retrieved > FRESHNESS_LIMIT:
        return "HOLD / NO ACTION", False, "The last real-data snapshot is stale; no current action is available."
    if pd.isna(input_row.get("spx_close")):
        return "HOLD / NO ACTION", False, "No observed SPX close for this session; no current action is available."
    if signal.get("risk_signal") not in ("RISK-ON", "NEUTRAL", "DE-RISK"):
        return "HOLD / NO ACTION", False, "The model has no valid daily action for this session."
    return pm_action(signal["risk_signal"]), True, None