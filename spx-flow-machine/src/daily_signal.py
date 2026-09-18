"""
Causal FREE daily regime signal using only persisted Yahoo Finance daily data.

Scores are transparent rolling empirical ranks, not calibrated probabilities.
Every value for date t is computed only from observations dated t or earlier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

try:
    from src.yahoo_daily_adapter import CANONICAL_COLUMNS, ingest_yahoo_daily
except ModuleNotFoundError:  # Direct execution: python src/daily_signal.py
    from yahoo_daily_adapter import CANONICAL_COLUMNS, ingest_yahoo_daily


MODEL_VERSION = "free_daily_regime_v1"
DEFAULT_START = "2010-01-01"
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


def score_daily_regimes(canonical: pd.DataFrame) -> pd.DataFrame:
    """Classify each date using causal rolling scores and fixed decision bands."""

    features = build_causal_features(canonical)
    body_components = {
        "weak_20d_trend": (
            _rolling_percentile(-features["spx_return_20d"]),
            0.25,
        ),
        "drawdown": (
            _rolling_percentile(-features["spx_drawdown_252d"]),
            0.25,
        ),
        "realized_volatility": (
            _rolling_percentile(features["spx_realized_vol_20d"]),
            0.20,
        ),
        "vix_level": (_rolling_percentile(features["vix_level"]), 0.20),
        "vix_acceleration": (
            _rolling_percentile(features["vix_change_5d"]),
            0.10,
        ),
    }
    tail_components = {
        "skew": (_rolling_percentile(features["skew_level"]), 0.30),
        "vvix": (_rolling_percentile(features["vvix_level"]), 0.30),
        "front_vol_inversion": (
            _rolling_percentile(features["vix9d_vix_ratio"]),
            0.20,
        ),
        "vix_curve_inversion": (
            _rolling_percentile(features["vix_vix3m_ratio"]),
            0.20,
        ),
    }

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
    result["risk_signal"] = np.select(
        [overall <= 35.0, overall >= 65.0],
        ["RISK-ON", "DE-RISK"],
        default="NEUTRAL",
    )
    result["regime"] = np.select(
        [overall <= 35.0, overall >= 65.0],
        ["CALM / RISK-ON", "STRESS / RISK-OFF"],
        default="TRANSITION / NEUTRAL",
    )
    result.loc[overall.isna(), ["risk_signal", "regime"]] = "INSUFFICIENT_DATA"
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


def refresh_free_signal(
    start: str,
    end: str,
    output_dir: str | Path,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Download FREE data, compute causal signals, and persist reproducible outputs."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    canonical, data_manifest = ingest_yahoo_daily(
        start,
        end,
        output_path / "daily_data",
        allow_missing_optional=True,
    )
    scored = score_daily_regimes(canonical)
    history = scored.loc[
        scored["overall_stress_score"].notna(),
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

    latest_data = canonical.iloc[-1]
    missing_inputs = [
        column
        for column in CANONICAL_COLUMNS[1:]
        if pd.isna(latest_data[column])
    ]
    data_lane = "AUGMENTED" if not missing_inputs else "CORE_FREE_DEGRADED"
    data_quality = (
        "COMPLETE"
        if not missing_inputs
        else "DEGRADED_MISSING_INPUTS"
    )
    history["data_lane"] = data_lane
    history["data_quality"] = data_quality
    history["missing_inputs"] = ",".join(missing_inputs)
    history = history.loc[:, list(SIGNAL_COLUMNS)]

    history_to_write = history.copy()
    history_to_write["date"] = pd.to_datetime(history_to_write["date"]).dt.date.astype(str)
    history_payload, history_checksum = _stable_csv(history_to_write)
    history_path = output_path / "signal_history.csv"
    history_path.write_text(history_payload, encoding="utf-8")

    latest = _json_safe_record(history_to_write.iloc[-1].to_dict())
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
    signal_manifest: dict[str, object] = {
        "status": "degraded" if missing_inputs else "complete",
        "model_version": MODEL_VERSION,
        "generated_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "requested_start_date": start,
        "requested_end_date": end,
        "input_source": "Yahoo Finance",
        "input_data_snapshot_id": data_manifest["snapshot"]["snapshot_id"],
        "input_data_manifest": "daily_data/metadata_manifest.json",
        "available_series": sorted(data_manifest["series"].keys()),
        "unavailable_series": data_manifest["unavailable_series"],
        "current_missing_inputs": missing_inputs,
        "data_lane": data_lane,
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
    return history, signal_manifest


def load_persisted_signal(
    output_dir: str | Path,
) -> tuple[dict[str, object] | None, pd.DataFrame]:
    output_path = Path(output_dir)
    latest_path = output_path / "latest_signal.json"
    history_path = output_path / "signal_history.csv"
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