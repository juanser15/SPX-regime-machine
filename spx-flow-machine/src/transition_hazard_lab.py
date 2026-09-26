"""Frozen-state transition hazards. Research replay only; never enters PM logic."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import rankdata

from src.free_signal_view import load_verified_real_signal
from src.regime_outlook_lab import (
    HORIZONS, INITIAL_TRAIN_SESSIONS, TEST_BLOCK_SESSIONS, rebuild_states,
    prove_prefix_invariance,
)
from src.daily_signal import score_daily_regimes

TARGETS = ("de_risk_entry", "any_transition", "de_risk_exit")
MODELS = ("unconditional", "state_duration", "market")
FEATURES = ("body_stress_score", "overall_stress_score")
L2 = 10.0
ALERT_TRAIN_QUANTILE = 0.90
SENSITIVITY_CUTOFFS = ((30, 70), (40, 60))


def state_frame(reconstructed: pd.DataFrame, canonical: pd.DataFrame) -> pd.DataFrame:
    """A run of state ends on an unobserved SPX session; no gap is bridged."""
    valid = canonical.loc[
        canonical["date"] <= pd.Timestamp(reconstructed["date"].iloc[-1]),
        ["date", "spx_close"],
    ].copy().reset_index(drop=True)
    valid["date"] = valid["date"].dt.strftime("%Y-%m-%d")
    valid = valid.merge(
        reconstructed[["date", "risk_signal", *FEATURES]],
        on="date", how="left", validate="one_to_one",
    )
    duration = []
    last, count = None, 0
    for row in valid.itertuples(index=False):
        state = row.risk_signal if pd.notna(row.spx_close) else None
        count = count + 1 if state is not None and state == last else (1 if state else 0)
        duration.append(count)
        last = state
    valid["duration"] = duration
    return valid


def make_risk_set(states: pd.DataFrame, target: str, horizon: int) -> pd.DataFrame:
    if target not in TARGETS or horizon not in HORIZONS:
        raise ValueError("Unknown target or horizon.")
    rows = []
    for i in range(len(states) - horizon):
        window = states.iloc[i:i + horizon + 1]
        current = window.iloc[0]
        if (window["spx_close"].isna().any()
                or window["risk_signal"].isna().any()
                or not np.isfinite(current[list(FEATURES)].astype(float).to_numpy()).all()):
            continue
        state = current["risk_signal"]
        if (target == "de_risk_entry" and state == "DE-RISK"
                or target == "de_risk_exit" and state != "DE-RISK"):
            continue
        future = window["risk_signal"].iloc[1:].tolist()
        if target == "de_risk_entry":
            event_offset = next((k for k, value in enumerate(future, 1) if value == "DE-RISK"), None)
        elif target == "de_risk_exit":
            event_offset = next((k for k, value in enumerate(future, 1) if value != "DE-RISK"), None)
        else:
            # Exact endpoint change, as specified by S_(t+h) != S_t;
            # a round-trip within h is not counted as an endpoint change.
            event_offset = horizon if future[-1] != state else None
        rows.append({
            "date": current["date"], "target_date": window.iloc[-1]["date"],
            "origin_idx": i, "target_idx": i + horizon,
            "origin_state": state, "duration": int(current["duration"]),
            "body_stress_score": float(current["body_stress_score"]),
            "overall_stress_score": float(current["overall_stress_score"]),
            "event": int(event_offset is not None),
            "first_event_date": (window.iloc[event_offset]["date"]
                                 if event_offset is not None else None),
        })
    return pd.DataFrame.from_records(rows)


def folds(samples: pd.DataFrame, horizon: int, sessions: int):
    for start in range(INITIAL_TRAIN_SESSIONS, sessions, TEST_BLOCK_SESSIONS):
        train = samples.loc[samples["target_idx"] < start - horizon].copy()
        test = samples.loc[
            (samples["origin_idx"] >= start)
            & (samples["origin_idx"] < start + TEST_BLOCK_SESSIONS)
        ].copy()
        if train.empty or test.empty:
            continue
        if train["target_idx"].max() + horizon >= test["origin_idx"].min():
            raise ValueError("Training labels violate the horizon embargo.")
        yield start, train, test


def matrix(frame: pd.DataFrame, model: str, means: np.ndarray,
           scales: np.ndarray) -> np.ndarray:
    state = frame["origin_state"]
    duration = np.log1p(frame["duration"].to_numpy(dtype=float))
    columns = [
        np.ones(len(frame)),
        state.eq("RISK-ON").to_numpy(dtype=float),
        state.eq("NEUTRAL").to_numpy(dtype=float),
        duration,
    ]
    if model == "market":
        raw = frame.loc[:, list(FEATURES)].to_numpy(dtype=float)
        if not np.isfinite(raw).all():
            raise ValueError("Missing causal market feature.")
        columns.extend(((raw - means) / scales).T)
    return np.column_stack(columns)


def fit(train: pd.DataFrame, test: pd.DataFrame, model: str) -> tuple[np.ndarray, np.ndarray]:
    """Same fixed regularization for both logistic specifications."""
    if model == "unconditional":
        # Jeffreys count prevents a zero/one training rate from producing infinite loss.
        value = (train["event"].sum() + 0.5) / (len(train) + 1)
        return np.full(len(test), value), np.full(len(train), value)
    raw = train.loc[:, list(FEATURES)].to_numpy(dtype=float)
    means, scales = raw.mean(axis=0), raw.std(axis=0)
    scales[scales == 0] = 1
    x = matrix(train, model, means, scales)
    xt = matrix(test, model, means, scales)
    y = train["event"].to_numpy(dtype=float)
    if y.sum() == 0 or y.sum() == len(y):
        raise ValueError("No two-class training evidence in this risk set.")
    penalty = np.ones(x.shape[1])
    penalty[0] = 0

    def objective(beta):
        z = x @ beta
        p = expit(z)
        loss = np.logaddexp(0, z).sum() - y @ z + L2 / 2 * np.sum((beta * penalty) ** 2)
        gradient = x.T @ (p - y) + L2 * beta * penalty
        return float(loss), gradient

    initial = np.zeros(x.shape[1])
    initial[0] = np.log(y.mean() / (1 - y.mean()))
    result = minimize(objective, initial, method="L-BFGS-B", jac=True,
                      options={"maxiter": 300, "ftol": 1e-11})
    if not result.success:
        raise RuntimeError(f"{model} binary hazard did not converge: {result.message}")
    return expit(xt @ result.x), expit(x @ result.x)


def replay(states: pd.DataFrame, targets=TARGETS, horizons=HORIZONS) -> pd.DataFrame:
    records = []
    for target in targets:
        for horizon in horizons:
            samples = make_risk_set(states, target, horizon)
            for start, train, test in folds(samples, horizon, len(states)):
                for model in MODELS:
                    scores, training_scores = fit(train, test, model)
                    threshold = (float(np.quantile(training_scores, ALERT_TRAIN_QUANTILE))
                                 if model == "market" else None)
                    for row, score in zip(test.itertuples(index=False), scores):
                        records.append({
                            "target": target, "horizon": horizon, "model": model,
                            "fold_start_idx": start,
                            "date": row.date, "target_date": row.target_date,
                            "origin_idx": row.origin_idx, "target_idx": row.target_idx,
                            "origin_state": row.origin_state, "duration": row.duration,
                            "event": row.event, "first_event_date": row.first_event_date,
                            "score": float(score), "train_top_decile_threshold": threshold,
                        })
    result = pd.DataFrame.from_records(records)
    if result.empty:
        raise ValueError("No chronological OOS transition hazards.")
    for (target, horizon), group in result.groupby(["target", "horizon"], sort=False):
        reference = group.loc[group["model"] == MODELS[0], ["date", "event"]].reset_index(drop=True)
        if any(not group.loc[group["model"] == model, ["date", "event"]]
               .reset_index(drop=True).equals(reference) for model in MODELS[1:]):
            raise ValueError(f"Different common OOS risk sets: {target} {horizon}.")
    return result


def checksums(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shadow_now_scores(states: pd.DataFrame) -> dict:
    """Research scores for last observed origins; refit on labels already complete."""
    current = states.iloc[-1]
    output = {"date": current["date"], "state": current["risk_signal"],
              "horizons": {}}
    if current["risk_signal"] == "DE-RISK":
        return output  # an entry is impossible while already in DE-RISK
    for horizon in HORIZONS:
        known = make_risk_set(states, "de_risk_entry", horizon)
        recent = []
        for idx in range(max(0, len(states) - 6), len(states)):
            origin = states.iloc[idx]
            if origin["risk_signal"] == "DE-RISK" or pd.isna(origin["spx_close"]):
                continue
            train = known.loc[known["target_idx"] < idx - horizon]
            sample = pd.DataFrame([{
                "origin_state": origin["risk_signal"],
                "duration": origin["duration"],
                **{feature: origin[feature] for feature in FEATURES},
            }])
            score, _ = fit(train, sample, "market")
            recent.append({"date": origin["date"], "score": float(score[0])})
        if recent:
            output["horizons"][str(horizon)] = {
                "score": recent[-1]["score"],
                "trend": ("rising" if len(recent) > 1 and recent[-1]["score"] > recent[-2]["score"]
                          else "falling" if len(recent) > 1 and recent[-1]["score"] < recent[-2]["score"]
                          else "flat / unavailable"),
                "recent_origin_scores": recent,
            }
    return output


def generate(source: Path, destination: Path) -> dict:
    """One snapshot-scoped research run. Never overwrite the frozen signal or old lab."""
    from src.transition_hazard_report import make_report, markdown_report

    bundle = load_verified_real_signal(source)
    signal_dir = source / "snapshots" / bundle.signal_snapshot_id
    input_dir = source / "daily_data" / "snapshots" / bundle.latest["data_snapshot_id"]
    reconstructed, canonical = rebuild_states(bundle, signal_dir)
    prefix = prove_prefix_invariance(canonical, score_daily_regimes(canonical))
    states = state_frame(reconstructed, canonical)
    predictions = replay(states)
    sensitivity = {}
    for low, high in SENSITIVITY_CUTOFFS:
        alternative = reconstructed.copy()
        score = alternative["overall_stress_score"]
        alternative["risk_signal"] = np.select(
            [score <= low, score >= high], ["RISK-ON", "DE-RISK"], default="NEUTRAL",
        )
        sensitivity[f"{low}/{high}"] = replay(
            state_frame(alternative, canonical), targets=("de_risk_entry",),
        )
    report, lead = make_report(predictions, states, sensitivity, prefix,
                               bundle.signal_snapshot_id, bundle.latest["data_snapshot_id"])
    report["shadow_now"] = shadow_now_scores(states)
    destination.mkdir(parents=True, exist_ok=True)
    final = destination / bundle.signal_snapshot_id
    if final.exists():
        raise FileExistsError("Transition research for this immutable snapshot already exists.")
    with tempfile.TemporaryDirectory(prefix=".transition-", dir=destination) as temp:
        staging = Path(temp)
        states.to_csv(staging / "research_states.csv", index=False, float_format="%.17g")
        predictions.to_csv(staging / "oos_predictions.csv", index=False, float_format="%.17g")
        lead.to_csv(staging / "de_risk_entry_leads.csv", index=False, float_format="%.17g")
        (staging / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
        (staging / "report.md").write_text(markdown_report(report))
        names = ("research_states.csv", "oos_predictions.csv", "de_risk_entry_leads.csv",
                 "report.json", "report.md")
        manifest = {
            "status": "TRANSITION RESEARCH / SHADOW ONLY",
            "signal_snapshot_id": bundle.signal_snapshot_id,
            "input_snapshot_id": bundle.latest["data_snapshot_id"],
            "source_signal_sha256": checksums(signal_dir / "signal_history.csv"),
            "source_canonical_sha256": checksums(input_dir / "canonical_daily.csv"),
            "files": {name: checksums(staging / name) for name in names},
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.replace(staging, final)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1]
                        / "data" / "free_signal")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]
                        / "research" / "transition_hazard")
    args = parser.parse_args()
    result = generate(args.source, args.output)
    print(json.dumps({key: {h: r["recommendation"] for h, r in rows.items()}
                      for key, rows in result["targets"].items()}, indent=2))