"""
Causal FREE daily regime signal using only persisted Yahoo Finance daily data.

Scores are transparent rolling empirical ranks, not calibrated probabilities.
Every value for date t is computed only from observations dated t or earlier.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    from src.yahoo_daily_adapter import CANONICAL_COLUMNS, ingest_yahoo_daily
except ModuleNotFoundError:  # Direct execution: python src/daily_signal.py
    from yahoo_daily_adapter import CANONICAL_COLUMNS, ingest_yahoo_daily


MODEL_VERSION = "free_daily_regime_v1"
DEFAULT_START = "2010-01-01"
BODY_WEIGHTS = {
    "weak_20d_trend": 0.25, "drawdown": 0.25,
    "realized_volatility": 0.20, "vix_level": 0.20, "vix_acceleration": 0.10,
}
TAIL_WEIGHTS = {
    "skew": 0.30, "vvix": 0.30,
    "front_vol_inversion": 0.20, "vix_curve_inversion": 0.20,
}
COMPONENT_TRANSFORMS = {
    "weak_20d_trend": ("spx_return_20d", -1, "-(SPX close / SPX close 20 rows ago - 1)"),
    "drawdown": ("spx_drawdown_252d", -1, "-(SPX close / rolling 252-row SPX max - 1)"),
    "realized_volatility": ("spx_realized_vol_20d", 1, "std(20 SPX one-row returns) × sqrt(252)"),
    "vix_level": ("vix_level", 1, "VIX close"),
    "vix_acceleration": ("vix_change_5d", 1, "VIX close / VIX close 5 rows ago - 1"),
    "skew": ("skew_level", 1, "SKEW close"),
    "vvix": ("vvix_level", 1, "VVIX close"),
    "front_vol_inversion": ("vix9d_vix_ratio", 1, "VIX9D close / VIX close"),
    "vix_curve_inversion": ("vix_vix3m_ratio", 1, "VIX close / VIX3M close"),
}
SIGNAL_COLUMNS = (
    "date",
    "data_lane",
    "regime",
    "risk_signal",
    "overall_stress_score",
    "body_stress_score",
    "tail_risk_hazard_score",
    "confidence_score",
    "confidence",
    "data_quality",
    "available_component_count",
    "missing_inputs",
    "primary_drivers",
    "score_type",
    "probability_status",
)


class SignalValidityError(RuntimeError):
    """The most recent completed session cannot support a real signal."""


def session_available_at(value: object) -> datetime:
    """Yahoo daily research becomes eligible six hours after the NY cash close."""
    session = pd.Timestamp(value).date()
    return (
        datetime.combine(session, time(16), ZoneInfo("America/New_York"))
        + timedelta(hours=6)
    ).astimezone(timezone.utc)


def _atomic_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".pending-", delete=False) as handle:
        pending = Path(handle.name)
        try:
            handle.write(payload)
        except BaseException:
            pending.unlink(missing_ok=True)
            raise
    os.replace(pending, path)


def _finalized_history_changes(
    previous_payload: str, candidate_payload: str, published_at: datetime,
) -> list[dict[str, object]]:
    previous = list(csv.DictReader(previous_payload.splitlines()))
    candidate = list(csv.DictReader(candidate_payload.splitlines()))
    if not previous or not candidate or previous[0].keys() != candidate[0].keys():
        return [{"date": "schema", "fields": ["columns"]}]
    by_date = {row["date"]: row for row in candidate}
    changes: list[dict[str, object]] = []
    for old in previous:
        date = old["date"]
        # A legacy pre-close row is retained in its immutable snapshot, not
        # promoted into the finalized-history guard.
        if session_available_at(date) > published_at:
            continue
        new = by_date.get(date)
        fields = (
            ["missing finalized date"] if new is None else
            [field for field in old if old[field] != new[field]]
        )
        if fields:
            changes.append({"date": date, "fields": fields})
    return changes


def _rolling_percentile(
    values: pd.Series, window: int = 252, min_periods: int = 60
) -> pd.Series:
    """Trailing percentile rank of the current value; no future observations."""

    def percentile_of_last(window_values: np.ndarray) -> float:
        current = window_values[-1]
        finite = window_values[np.isfinite(window_values)]
        if not np.isfinite(current) or len(finite) == 0:
            return np.nan
        return float(np.mean(finite <= current) * 100.0)

    return values.astype(float).rolling(window, min_periods=min_periods).apply(
        percentile_of_last, raw=True
    )


def _weighted_available(
    components: Mapping[str, tuple[pd.Series, float]],
) -> tuple[pd.Series, pd.Series]:
    """Weighted mean over the components available on each date."""

    first = next(iter(components.values()))[0]
    numerator = pd.Series(0.0, index=first.index)
    denominator = pd.Series(0.0, index=first.index)
    count = pd.Series(0, index=first.index, dtype=int)
    for series, weight in components.values():
        available = series.notna()
        numerator = numerator.add(series.fillna(0.0) * weight)
        denominator = denominator.add(available.astype(float) * weight)
        count = count.add(available.astype(int))
    score = numerator.div(denominator.replace(0.0, np.nan))
    return score, count


def build_causal_features(canonical: pd.DataFrame) -> pd.DataFrame:
    """Build the agreed daily features with trailing-only calculations."""

    data = canonical.copy().sort_values("date", kind="mergesort").reset_index(drop=True)
    spx = pd.to_numeric(data["spx_close"], errors="coerce")
    spx_return_1d = spx.pct_change(fill_method=None)

    features = pd.DataFrame({"date": data["date"]})
    features["spx_return_1d"] = spx_return_1d
    for horizon in (5, 20, 60):
        features[f"spx_return_{horizon}d"] = spx.pct_change(
            horizon, fill_method=None
        )
    features["spx_ma20_gap"] = spx.div(
        spx.rolling(20, min_periods=20).mean()
    ) - 1.0
    features["spx_drawdown_252d"] = spx.div(
        spx.rolling(252, min_periods=20).max()
    ) - 1.0
    for horizon in (10, 20, 60):
        features[f"spx_realized_vol_{horizon}d"] = (
            spx_return_1d.rolling(horizon, min_periods=horizon).std()
            * np.sqrt(252.0)
        )

    vix = pd.to_numeric(data["vix_close"], errors="coerce")
    features["vix_level"] = vix
    features["vix_change_5d"] = vix.pct_change(5, fill_method=None)
    features["vix9d_vix_ratio"] = pd.to_numeric(
        data["vix9d_close"], errors="coerce"
    ).div(vix)
    features["vix_vix3m_ratio"] = vix.div(
        pd.to_numeric(data["vix3m_close"], errors="coerce")
    )
    features["vvix_level"] = pd.to_numeric(data["vvix_close"], errors="coerce")
    features["skew_level"] = pd.to_numeric(data["skew_close"], errors="coerce")
    return features


def _component_scores(features: pd.DataFrame):
    """Exact component ranks used by the frozen v1 score and audit view."""
    body = {
        "weak_20d_trend": _rolling_percentile(-features["spx_return_20d"]),
        "drawdown": _rolling_percentile(-features["spx_drawdown_252d"]),
        "realized_volatility": _rolling_percentile(features["spx_realized_vol_20d"]),
        "vix_level": _rolling_percentile(features["vix_level"]),
        "vix_acceleration": _rolling_percentile(features["vix_change_5d"]),
    }
    tail = {
        "skew": _rolling_percentile(features["skew_level"]),
        "vvix": _rolling_percentile(features["vvix_level"]),
        "front_vol_inversion": _rolling_percentile(features["vix9d_vix_ratio"]),
        "vix_curve_inversion": _rolling_percentile(features["vix_vix3m_ratio"]),
    }
    return (
        {name: (series, BODY_WEIGHTS[name]) for name, series in body.items()},
        {name: (series, TAIL_WEIGHTS[name]) for name, series in tail.items()},
    )


def risk_signal_for_score(score: object) -> str:
    """The frozen research bands; NEUTRAL is displayed as HOLD / NO ACTION."""
    if pd.isna(score):
        return "INSUFFICIENT_DATA"
    if float(score) <= 35.0:
        return "RISK-ON"
    if float(score) >= 65.0:
        return "DE-RISK"
    return "NEUTRAL"


def component_details(row: pd.Series) -> list[dict[str, object]]:
    """Percentile, raw weight and effective overall weight for each used input."""
    body = [(name, float(row[f"component_{name}"]), weight) for name, weight in BODY_WEIGHTS.items()
            if pd.notna(row[f"component_{name}"])]
    tail = [(name, float(row[f"component_{name}"]), weight) for name, weight in TAIL_WEIGHTS.items()
            if pd.notna(row[f"component_{name}"])]
    details = []
    for group, members, group_share in (
        ("body", body, 0.75 if tail else 1.0),
        ("tail", tail, 0.25 if tail else 0.0),
    ):
        total_weight = sum(weight for _, _, weight in members)
        for name, percentile, weight in members:
            effective = group_share * weight / total_weight
            feature, sign, transformation = COMPONENT_TRANSFORMS[name]
            details.append({
                "name": name, "group": group, "percentile_score": percentile,
                "transformation": transformation,
                "transformed_value": float(row[feature]) * sign,
                "base_weight": weight, "effective_weight": effective,
                "weighted_points": percentile * effective,
            })
    return details


def score_daily_regimes(canonical: pd.DataFrame) -> pd.DataFrame:
    """Classify each date using causal rolling scores and fixed decision bands."""

    features = build_causal_features(canonical)
    body_components, tail_components = _component_scores(features)

    body_score, body_count = _weighted_available(body_components)
    tail_score, tail_count = _weighted_available(tail_components)
    overall = body_score.where(
        tail_score.isna(), body_score * 0.75 + tail_score * 0.25
    )
    component_count = body_count + tail_count
    component_coverage = component_count / float(
        len(body_components) + len(tail_components)
    )
    distance_score = ((overall - 50.0).abs() * 2.0).clip(upper=100.0)
    confidence_score = (
        distance_score * 0.65 + component_coverage * 100.0 * 0.35
    ).clip(upper=100.0)

    result = features.copy()
    result["body_stress_score"] = body_score
    result["tail_risk_hazard_score"] = tail_score
    result["overall_stress_score"] = overall
    result["available_component_count"] = component_count
    result["confidence_score"] = confidence_score
    result["risk_signal"] = overall.map(risk_signal_for_score)
    result["regime"] = np.select(
        [overall <= 35.0, overall >= 65.0],
        ["CALM / RISK-ON", "STRESS / RISK-OFF"],
        default="TRANSITION / NEUTRAL",
    )
    result.loc[overall.isna(), "regime"] = "INSUFFICIENT_DATA"
    result["confidence"] = np.select(
        [confidence_score >= 70.0, confidence_score >= 45.0],
        ["HIGH", "MEDIUM"],
        default="LOW",
    )
    result["score_type"] = "causal_empirical_score_not_probability"
    result["probability_status"] = "NOT_CALIBRATED"

    component_scores = {
        name: series for name, (series, _weight) in {**body_components, **tail_components}.items()
    }
    for name, series in component_scores.items():
        result[f"component_{name}"] = series
    drivers: list[str] = []
    for row_index in result.index:
        ranked = sorted(
            (
                (abs(float(series.loc[row_index]) - 50.0), name, float(series.loc[row_index]))
                for name, series in component_scores.items()
                if pd.notna(series.loc[row_index])
            ),
            reverse=True,
        )[:3]
        drivers.append(
            "; ".join(
                f"{name}={value:.0f} ({'raises' if value >= 50.0 else 'reduces'} stress)"
                for _distance, name, value in ranked
            )
        )
    result["primary_drivers"] = drivers
    return result


def _stable_csv(frame: pd.DataFrame) -> tuple[str, str]:
    payload = frame.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_safe_record(record: Mapping[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in record.items():
        if value is None or pd.isna(value):
            safe[key] = None
        elif isinstance(value, (pd.Timestamp, datetime)):
            safe[key] = value.date().isoformat()
        elif hasattr(value, "item"):
            safe[key] = value.item()
        else:
            safe[key] = value
    return safe


def _audit_payload(
    history: pd.DataFrame,
    scored: pd.DataFrame,
    *,
    signal_snapshot_id: str,
    input_snapshot_id: str,
    retrieved_at: str,
    calculated_at: str,
) -> str:
    """One immutable research record per row; availability never predates calculation."""
    scored_by_date = scored.set_index(scored["date"].dt.date.astype(str))
    retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    calculated = datetime.fromisoformat(calculated_at.replace("Z", "+00:00"))
    if retrieved.tzinfo is None or calculated.tzinfo is None:
        raise ValueError("Audit timestamps must include UTC offsets.")
    if scored_by_date.index.has_duplicates:
        raise ValueError("Duplicate scored dates cannot be audited.")
    records = []
    for _, row in history.iterrows():
        date = str(row["date"])[:10]
        if date not in scored_by_date.index:
            raise ValueError(f"Missing component scores for {date}.")
        model_row = scored_by_date.loc[date]
        details = component_details(model_row)
        if (row["risk_signal"] != model_row["risk_signal"]
                or row["primary_drivers"] != model_row["primary_drivers"]
                or int(row["available_component_count"]) != int(model_row["available_component_count"])):
            raise ValueError(f"Persisted action or drivers do not match the model for {date}.")
        for field in ("overall_stress_score", "body_stress_score",
                      "tail_risk_hazard_score", "confidence_score"):
            stored, recomputed = row[field], model_row[field]
            if pd.isna(stored) and pd.isna(recomputed):
                continue
            if pd.isna(stored) or pd.isna(recomputed) or not np.isclose(
                    float(stored), float(recomputed), atol=1e-6, rtol=0
            ):
                raise ValueError(f"Persisted {field} does not match the model for {date}.")
        if not np.isclose(sum(item["weighted_points"] for item in details),
                          float(row["overall_stress_score"]), atol=1e-6, rtol=0):
            raise ValueError(f"Component scores do not reproduce the persisted score for {date}.")
        close = datetime.combine(
            datetime.fromisoformat(date).date(), time(16), ZoneInfo("America/New_York"),
        ) + timedelta(hours=6)
        available_at = max(close, retrieved, calculated)
        records.append({
            "date": date,
            "calculated_at_utc": calculated.astimezone(timezone.utc).isoformat(),
            "available_at_utc": available_at.astimezone(timezone.utc).isoformat(),
            "source_retrieved_at_utc": retrieved.astimezone(timezone.utc).isoformat(),
            "model_version": MODEL_VERSION,
            "source": "Yahoo Finance historical daily (not live)",
            "input_data_snapshot_id": input_snapshot_id,
            "signal_snapshot_id": signal_snapshot_id,
            "risk_signal": str(row["risk_signal"]),
            "action": {
                "RISK-ON": "RISK-ON", "NEUTRAL": "HOLD / NO ACTION",
                "DE-RISK": "DE-RISK",
            }[str(row["risk_signal"])],
            "overall_stress_score": float(row["overall_stress_score"]),
            "body_stress_score": float(row["body_stress_score"]),
            "tail_risk_hazard_score": (
                float(row["tail_risk_hazard_score"])
                if pd.notna(row["tail_risk_hazard_score"]) else None
            ),
            "confidence_score": float(row["confidence_score"]),
            "confidence": str(row["confidence"]),
            "data_quality": str(row["data_quality"]),
            "missing_inputs": (
                [part for part in str(row["missing_inputs"]).split(",") if part]
                if pd.notna(row["missing_inputs"]) else []
            ),
            "primary_drivers": (
                [part.strip() for part in str(row["primary_drivers"]).split(";") if part.strip()]
                if pd.notna(row["primary_drivers"]) else []
            ),
            "components": details,
            "research_only": True,
            "probability_status": "NOT_CALIBRATED",
        })
    return "".join(json.dumps(item, sort_keys=True, allow_nan=False) + "\n" for item in records)


def write_snapshot_audit(
    output_dir: str | Path, signal_snapshot_id: str | None = None,
) -> Path:
    """Create a deterministic sidecar for an already persisted immutable snapshot."""
    output_path = Path(output_dir)
    signal_id = signal_snapshot_id or json.loads(
        (output_path / "signal_manifest.json").read_text()
    )["signal_snapshot_id"]
    snap = output_path / "snapshots" / signal_id
    manifest = json.loads((snap / "signal_manifest.json").read_text())
    if manifest["signal_snapshot_id"] != signal_id:
        raise ValueError("Cannot audit a mismatched signal snapshot.")
    history_bytes = (snap / "signal_history.csv").read_bytes()
    if hashlib.sha256(history_bytes).hexdigest() != manifest["signal_history_sha256"]:
        raise ValueError("Cannot audit a signal snapshot with a mismatched checksum.")
    input_id = manifest["input_data_snapshot_id"]
    input_dir = output_path / "daily_data" / "snapshots" / input_id
    data_manifest = json.loads((input_dir / "metadata_manifest.json").read_text())
    canonical_bytes = (input_dir / "canonical_daily.csv").read_bytes()
    latest = json.loads((snap / "latest_signal.json").read_text())
    if (data_manifest["source"] != "Yahoo Finance"
            or data_manifest["snapshot"]["snapshot_id"] != input_id
            or latest.get("data_snapshot_id") != input_id
            or latest.get("retrieved_at_utc") != data_manifest.get("retrieved_at_utc")
            or hashlib.sha256(canonical_bytes).hexdigest() != data_manifest["canonical_sha256"]):
        raise ValueError("Cannot audit unverified real input data.")
    canonical = pd.read_csv(input_dir / "canonical_daily.csv", parse_dates=["date"])
    history = pd.read_csv(snap / "signal_history.csv")
    scored = score_daily_regimes(canonical)
    payload = _audit_payload(
        history, scored, signal_snapshot_id=signal_id, input_snapshot_id=input_id,
        retrieved_at=data_manifest["retrieved_at_utc"],
        calculated_at=manifest["generated_at_utc"],
    )
    audit = output_path / "audits" / f"{signal_id}.jsonl"
    if audit.exists():
        if audit.read_text() != payload:
            raise ValueError("Immutable signal audit differs from the verified snapshot.")
    else:
        audit.parent.mkdir(parents=True, exist_ok=True)
        audit.write_text(payload, encoding="utf-8")
    return audit


def _build_signal_candidate(
    start: str,
    end: str,
    output_path: Path,
    canonical: pd.DataFrame,
    data_manifest: dict[str, object],
    now: datetime,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build a complete candidate only in a private staging directory."""
    scored = score_daily_regimes(canonical)
    retrieved = datetime.fromisoformat(str(data_manifest["retrieved_at_utc"]))
    if retrieved.tzinfo is None:
        raise ValueError("Yahoo retrieval timestamp must include its timezone.")
    cutoff = min(now, retrieved.astimezone(timezone.utc))
    eligible = canonical.loc[
        canonical["date"].map(lambda date: session_available_at(date) <= cutoff)
    ]
    if eligible.empty:
        raise SignalValidityError("No completed US cash-market session is available.")
    latest_eligible = eligible.iloc[-1]
    latest_score = scored.loc[scored["date"] == latest_eligible["date"]]
    if (
        pd.isna(latest_eligible["spx_close"])
        or len(latest_score) != 1
        or pd.isna(latest_score.iloc[0]["overall_stress_score"])
        or pd.isna(latest_score.iloc[0]["body_stress_score"])
        or int(latest_score.iloc[0]["available_component_count"]) < 1
        or latest_score.iloc[0]["risk_signal"] not in ("RISK-ON", "NEUTRAL", "DE-RISK")
    ):
        raise SignalValidityError(
            f"{pd.Timestamp(latest_eligible['date']).date()}: "
            "SIGNAL UNAVAILABLE — DATA FAILURE / INSUFFICIENT REAL DATA"
        )
    history = scored.loc[
        scored["overall_stress_score"].notna()
        & scored["date"].map(lambda date: session_available_at(date) <= cutoff),
        [
            "date",
            "regime",
            "risk_signal",
            "overall_stress_score",
            "body_stress_score",
            "tail_risk_hazard_score",
            "confidence_score",
            "confidence",
            "available_component_count",
            "primary_drivers",
            "score_type",
            "probability_status",
        ],
    ].copy()
    if history.empty:
        raise RuntimeError(
            "Insufficient real Yahoo history to compute a causal FREE daily signal."
        )

    # Quality is deliberately evaluated against the same calendar row as each
    # signal.  Do not copy the latest row's status backwards through history.
    canonical_by_date = canonical.set_index("date")
    unavailable = data_manifest.get("unavailable_series", {})
    per_date_quality: list[dict[str, object]] = []
    row_lanes: list[str] = []
    row_quality: list[str] = []
    row_missing: list[str] = []
    for date in history["date"]:
        source_row = canonical_by_date.loc[date]
        missing = [
            column for column in CANONICAL_COLUMNS[1:] if pd.isna(source_row[column])
        ]
        reasons = {
            column: (
                str(unavailable[column].get("reason", "unavailable"))
                if column in unavailable
                else "missing Close for this date"
            )
            for column in missing
        }
        quality = "COMPLETE" if not missing else "DEGRADED_MISSING_INPUTS"
        lane = "AUGMENTED" if not missing else "CORE_FREE_DEGRADED"
        row_lanes.append(lane)
        row_quality.append(quality)
        row_missing.append(",".join(missing))
        per_date_quality.append(
            {
                "date": pd.Timestamp(date).date().isoformat(),
                "data_quality": quality,
                "data_lane": lane,
                "missing_inputs": missing,
                "missing_component_reasons": reasons,
                # Yahoo historical/backfill data is never live-deployable,
                # even when every component happens to be present.  Keep
                # component quality separate from this source-policy gate.
                "component_quality": "COMPLETE" if not missing else "DEGRADED",
                "research_status": "RESEARCH_ONLY",
                "deployable": False,
            }
        )
    history["data_lane"] = row_lanes
    history["data_quality"] = row_quality
    history["missing_inputs"] = row_missing
    history = history.loc[:, list(SIGNAL_COLUMNS)]

    history_to_write = history.copy()
    history_to_write["date"] = pd.to_datetime(history_to_write["date"]).dt.date.astype(str)
    history_payload, history_checksum = _stable_csv(history_to_write)
    history_path = output_path / "signal_history.csv"
    history_path.write_text(history_payload, encoding="utf-8")

    latest = _json_safe_record(history_to_write.iloc[-1].to_dict())
    latest_quality = per_date_quality[-1]
    latest.update(
        {
            "missing_component_reasons": latest_quality["missing_component_reasons"],
            "research_status": latest_quality["research_status"],
            "component_quality": latest_quality["component_quality"],
            "deployable": False,
        }
    )
    latest["retrieved_at_utc"] = data_manifest["retrieved_at_utc"]
    latest["data_snapshot_id"] = data_manifest["snapshot"]["snapshot_id"]
    latest["model_version"] = MODEL_VERSION
    latest_path = output_path / "latest_signal.json"
    latest_path.write_text(
        json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    signal_snapshot_id = hashlib.sha256(
        f"{data_manifest['snapshot']['snapshot_id']}:{history_checksum}:{MODEL_VERSION}".encode()
    ).hexdigest()
    latest_missing_inputs = list(latest_quality["missing_inputs"])
    any_degraded = any(item["data_quality"] != "COMPLETE" for item in per_date_quality)
    signal_manifest: dict[str, object] = {
        "status": "degraded" if any_degraded else "complete",
        "model_version": MODEL_VERSION,
        "generated_at_utc": now.isoformat(),
        "requested_start_date": start,
        "requested_end_date": end,
        "input_source": "Yahoo Finance historical daily (not live)",
        "input_data_snapshot_id": data_manifest["snapshot"]["snapshot_id"],
        "input_data_manifest": (
            f"daily_data/snapshots/{data_manifest['snapshot']['snapshot_id']}/metadata_manifest.json"
        ),
        "available_series": sorted(data_manifest["series"].keys()),
        "unavailable_series": data_manifest["unavailable_series"],
        "current_missing_inputs": latest_missing_inputs,
        "data_lane": latest_quality["data_lane"],
        "research_status": "RESEARCH_ONLY",
        "deployable": False,
        "per_date_quality": per_date_quality,
        "causality": (
            "Trailing-only rolling calculations; no smoothing, Viterbi, "
            "future labels, imputation, or full-sample parameter estimation."
        ),
        "score_semantics": (
            "Empirical trailing percentile scores on a 0-100 stress scale; "
            "not calibrated probabilities."
        ),
        "decision_bands": {
            "RISK-ON": "overall_stress_score <= 35",
            "NEUTRAL": "35 < overall_stress_score < 65",
            "DE-RISK": "overall_stress_score >= 65",
        },
        "signal_history_file": history_path.name,
        "signal_history_sha256": history_checksum,
        "latest_signal_file": latest_path.name,
        "signal_snapshot_id": signal_snapshot_id,
    }
    manifest_path = output_path / "signal_manifest.json"
    manifest_path.write_text(
        json.dumps(signal_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    snapshot_path = output_path / "snapshots" / signal_snapshot_id
    if not snapshot_path.exists():
        snapshot_path.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(history_path, snapshot_path / history_path.name)
        shutil.copyfile(latest_path, snapshot_path / latest_path.name)
        shutil.copyfile(manifest_path, snapshot_path / manifest_path.name)
    # Reuse the immutable snapshot's calculation time for an identical rerun.
    snapshot_manifest = json.loads((snapshot_path / manifest_path.name).read_text())
    audit_payload = _audit_payload(
        pd.read_csv(history_path), scored, signal_snapshot_id=signal_snapshot_id,
        input_snapshot_id=data_manifest["snapshot"]["snapshot_id"],
        retrieved_at=data_manifest["retrieved_at_utc"],
        calculated_at=snapshot_manifest["generated_at_utc"],
    )
    audit = output_path / "audits" / f"{signal_snapshot_id}.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    if audit.exists():
        if audit.read_text() != audit_payload:
            raise ValueError("Immutable signal audit differs from the verified snapshot.")
    else:
        audit.write_text(audit_payload, encoding="utf-8")
    return history, signal_manifest


def refresh_free_signal(
    start: str, end: str, output_dir: str | Path, *,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Stage Yahoo data and calculations; switch the verified pointer only on success."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    with (output_path / ".refresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _refresh_locked(start, end, output_path, now)


def _refresh_locked(
    start: str, end: str, output_path: Path, now: datetime,
) -> tuple[pd.DataFrame, dict[str, object]]:
    with tempfile.TemporaryDirectory(prefix=".staged-refresh-", dir=output_path) as name:
        staged = Path(name)
        canonical, data_manifest = ingest_yahoo_daily(
            start, end, staged / "daily_data", allow_missing_optional=True,
        )
        input_id = data_manifest["snapshot"]["snapshot_id"]
        staged_input = staged / "daily_data" / "snapshots" / input_id
        if not staged_input.is_dir():
            raise RuntimeError("Yahoo input snapshot was not staged; publication refused.")
        # Score exactly the persisted float representation that the immutable
        # audit will later verify; in-memory downloader values may roundtrip
        # differently through CSV.
        canonical = pd.read_csv(staged_input / "canonical_daily.csv", parse_dates=["date"])
        published_input = output_path / "daily_data" / "snapshots" / input_id
        if published_input.exists():
            archived_manifest = json.loads(
                (published_input / "metadata_manifest.json").read_text()
            )
            if (archived_manifest["canonical_sha256"] != data_manifest["canonical_sha256"]
                    or archived_manifest["snapshot"]["snapshot_id"] != input_id):
                raise RuntimeError("Existing immutable Yahoo input snapshot differs.")
            # The same content ID may already have a different retrieval timestamp.
            # Use its immutable provenance, not the discarded staging timestamp.
            data_manifest = archived_manifest
        try:
            history, manifest = _build_signal_candidate(
                start, end, staged, canonical, data_manifest, now,
            )
        except SignalValidityError as error:
            failed_dir = output_path / "provisional_inputs" / input_id
            if not published_input.exists() and not failed_dir.exists():
                failed_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(staged_input, failed_dir)
            pointer = output_path / "signal_manifest.json"
            published_id = (
                json.loads(pointer.read_text())["signal_snapshot_id"]
                if pointer.exists() else None
            )
            _atomic_text(
                output_path / "refresh_status.json",
                json.dumps({
                    "status": "insufficient_real_data",
                    "reason": str(error),
                    "date": str(canonical["date"].max().date()),
                    "retrieved_at_utc": data_manifest["retrieved_at_utc"],
                    "published_signal_snapshot_id": published_id,
                }, sort_keys=True, indent=2) + "\n",
            )
            logging.warning("Yahoo signal unavailable: %s", error)
            raise

        pointer = output_path / "signal_manifest.json"
        if pointer.exists():
            previous_manifest = json.loads(pointer.read_text())
            previous_dir = output_path / "snapshots" / previous_manifest["signal_snapshot_id"]
            previous_payload = (previous_dir / "signal_history.csv").read_text()
            if hashlib.sha256(previous_payload.encode()).hexdigest() != previous_manifest["signal_history_sha256"]:
                raise RuntimeError("Previously published signal checksum differs; publication refused.")
            differences = _finalized_history_changes(
                previous_payload,
                (staged / "signal_history.csv").read_text(),
                datetime.fromisoformat(previous_manifest["generated_at_utc"]),
            )
            if differences:
                review_dir = output_path / "revision_reviews" / input_id
                if not review_dir.exists():
                    review_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(staged_input, review_dir)
                    (review_dir / "review.json").write_text(
                        json.dumps({
                            "status": "requires_explicit_review",
                            "detected_at_utc": now.isoformat(),
                            "changes": differences,
                        }, indent=2, sort_keys=True) + "\n"
                    )
                logging.warning(
                    "Yahoo vendor revision requires explicit review: %s", differences[:10],
                )
                raise RuntimeError(
                    "Finalized research history changed; refusing to silently revise "
                    f"prior signals: {differences[:10]}"
                )

        published_input.parent.mkdir(parents=True, exist_ok=True)
        if not published_input.exists():
            os.replace(staged_input, published_input)
        signal_id = manifest["signal_snapshot_id"]
        published_signal = output_path / "snapshots" / signal_id
        published_signal.parent.mkdir(parents=True, exist_ok=True)
        signal_existed = published_signal.exists()
        if signal_existed:
            old_manifest = json.loads((published_signal / "signal_manifest.json").read_text())
            if (old_manifest["signal_history_sha256"] != manifest["signal_history_sha256"]
                    or old_manifest["input_data_snapshot_id"] != input_id):
                raise RuntimeError("Existing immutable signal snapshot differs.")
            manifest = old_manifest
        else:
            os.replace(staged / "snapshots" / signal_id, published_signal)
        published_audit = output_path / "audits" / f"{signal_id}.jsonl"
        published_audit.parent.mkdir(parents=True, exist_ok=True)
        if not signal_existed and not published_audit.exists():
            os.replace(staged / "audits" / f"{signal_id}.jsonl", published_audit)
        write_snapshot_audit(output_path, signal_id)

        # Legacy flat files remain readable, but the root manifest is the only
        # published pointer. All serving paths read the immutable directories.
        for file_name in ("canonical_daily.csv", "coverage_report.json", "metadata_manifest.json"):
            _atomic_text(
                output_path / "daily_data" / file_name,
                (published_input / file_name).read_text(),
            )
        for raw in (published_input / "raw").glob("*.csv"):
            _atomic_text(output_path / "daily_data" / "raw" / raw.name, raw.read_text())
        for file_name in ("signal_history.csv", "latest_signal.json"):
            _atomic_text(output_path / file_name, (published_signal / file_name).read_text())
        _atomic_text(pointer, (published_signal / "signal_manifest.json").read_text())
        return history, manifest


def load_persisted_signal(
    output_dir: str | Path,
) -> tuple[dict[str, object] | None, pd.DataFrame]:
    output_path = Path(output_dir)
    pointer = output_path / "signal_manifest.json"
    if not pointer.exists():
        return None, pd.DataFrame()
    signal_id = json.loads(pointer.read_text())["signal_snapshot_id"]
    latest_path = output_path / "snapshots" / signal_id / "latest_signal.json"
    history_path = output_path / "snapshots" / signal_id / "signal_history.csv"
    if not latest_path.exists() or not history_path.exists():
        return None, pd.DataFrame()
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    history = pd.read_csv(history_path, parse_dates=["date"])
    return latest, history


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the FREE daily SPX regime signal.")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", required=True, help="Exclusive Yahoo end date.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "free_signal",
    )
    args = parser.parse_args(argv)
    history, manifest = refresh_free_signal(args.start, args.end, args.output_dir)
    print(
        json.dumps(
            {
                "as_of": history.iloc[-1]["date"].date().isoformat(),
                "risk_signal": history.iloc[-1]["risk_signal"],
                "regime": history.iloc[-1]["regime"],
                "data_lane": manifest["data_lane"],
                "output_dir": str(args.output_dir),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())