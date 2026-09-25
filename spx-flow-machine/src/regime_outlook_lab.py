"""Frozen-v1 regime-transition research replay. Never called by PM decision logic."""

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
from scipy.special import logsumexp

from src.daily_signal import MODEL_VERSION, score_daily_regimes, session_available_at
from src.free_signal_view import load_verified_real_signal

STATES = ("RISK-ON", "NEUTRAL", "DE-RISK")
HORIZONS = (1, 3, 5)
MODELS = ("persistence", "unconditional", "markov", "logistic")
FEATURES = ("body_stress_score", "overall_stress_score")
INITIAL_TRAIN_SESSIONS = 1260  # fixed before OOS replay; ~five observed trading years
TEST_BLOCK_SESSIONS = 252
LOGISTIC_L2 = 10.0  # fixed, not tuned on test folds
SCORE_FLOOR = 1e-6  # scoring-only clipping for deterministic persistence log loss
ALARM_LEVEL = 0.50
CALIBRATION_BINS = np.linspace(0, 1, 6)


def rebuild_states(bundle, signal_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Exactly replay frozen v1 from verified serialized Yahoo inputs, not forecasts."""
    canonical = bundle.canonical.copy()
    canonical["date"] = pd.to_datetime(canonical["date"])
    canonical = canonical.sort_values("date").reset_index(drop=True)
    if canonical["date"].duplicated().any():
        raise ValueError("Duplicate canonical sessions.")
    scored = score_daily_regimes(canonical)
    history = bundle.history.copy()
    history["date"] = pd.to_datetime(history["date"])
    rows = scored.set_index("date").loc[history["date"]].reset_index()
    if list(rows["date"]) != list(history["date"]):
        raise ValueError("Reconstruction does not align with persisted sessions.")
    if not rows["risk_signal"].eq(history["risk_signal"]).all():
        raise ValueError("Frozen v1 reconstruction disagrees with persisted states.")
    for field in ("overall_stress_score", "body_stress_score", "tail_risk_hazard_score"):
        if not np.allclose(rows[field], history[field], atol=1e-6, rtol=0, equal_nan=True):
            raise ValueError(f"Frozen v1 reconstruction disagrees with persisted {field}.")
    if not rows["risk_signal"].isin(STATES).all():
        raise ValueError("Only three valid frozen-v1 states may enter the lab.")

    manifest = json.loads((signal_dir / "signal_manifest.json").read_text())
    retrieved = pd.Timestamp(bundle.latest["retrieved_at_utc"])
    calculated = pd.Timestamp(manifest["generated_at_utc"])
    if retrieved.tzinfo is None or calculated.tzinfo is None:
        raise ValueError("Snapshot availability timestamps must be timezone-aware.")
    available = [
        max(session_available_at(date), retrieved.to_pydatetime(), calculated.to_pydatetime())
        for date in rows["date"]
    ]
    reconstructed = pd.DataFrame({
        "date": rows["date"].dt.strftime("%Y-%m-%d"),
        "risk_signal": rows["risk_signal"],
        "overall_stress_score": rows["overall_stress_score"],
        "body_stress_score": rows["body_stress_score"],
        "source_retrieved_at_utc": retrieved.isoformat(),
        "calculated_at_utc": calculated.isoformat(),
        "available_at_utc": [value.isoformat() for value in available],
        "research_status": "RESEARCH RECONSTRUCTION",
        "model_version": MODEL_VERSION,
        "input_snapshot_id": bundle.latest["data_snapshot_id"],
        "signal_snapshot_id": bundle.signal_snapshot_id,
    })
    return reconstructed, canonical


def prove_prefix_invariance(canonical: pd.DataFrame, full: pd.DataFrame) -> list[dict]:
    """Compare real historical prefixes with the same full-snapshot replay."""
    checks = []
    for size in (800, 1600, 2600, 3600):
        if size >= len(canonical):
            continue
        prefix = score_daily_regimes(canonical.iloc[:size].copy())
        expected = full.iloc[:size]
        if (not prefix["risk_signal"].eq(expected["risk_signal"]).all()
                or not np.allclose(prefix["overall_stress_score"],
                                   expected["overall_stress_score"],
                                   atol=1e-10, rtol=0, equal_nan=True)):
            raise ValueError(f"Appending later real observations changed a prefix of {size} sessions.")
        checks.append({"prefix_rows": size, "changed_states": 0, "changed_scores": 0})
    if not checks:
        raise ValueError("Not enough real history for a prefix-invariance check.")
    return checks


def build_samples(reconstructed: pd.DataFrame, canonical: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Exact h next canonical sessions; never skip a missing observed SPX row."""
    if horizon not in HORIZONS:
        raise ValueError("Unregistered horizon.")
    source = canonical.loc[
        canonical["date"] <= pd.Timestamp(reconstructed["date"].iloc[-1]),
        ["date", "spx_close"],
    ].copy().reset_index(drop=True)
    known = reconstructed.set_index("date")
    rows = []
    for i in range(len(source) - horizon):
        window = source.iloc[i:i + horizon + 1]
        if window["spx_close"].isna().any():
            continue
        origin, target = window.iloc[0]["date"].strftime("%Y-%m-%d"), window.iloc[-1]["date"].strftime("%Y-%m-%d")
        if origin not in known.index or target not in known.index:
            continue
        current, destination = known.loc[origin], known.loc[target]
        if (current["risk_signal"] not in STATES or destination["risk_signal"] not in STATES
                or any(pd.isna(current[field]) for field in FEATURES)):
            continue
        rows.append({
            "date": origin, "target_date": target,
            "origin_idx": i, "target_idx": i + horizon,
            "origin_state": current["risk_signal"],
            "target_state": destination["risk_signal"],
            "body_stress_score": float(current["body_stress_score"]),
            "overall_stress_score": float(current["overall_stress_score"]),
            "origin_available_at_utc": current["available_at_utc"],
        })
    return pd.DataFrame.from_records(rows)


def walk_forward_folds(samples: pd.DataFrame, horizon: int, session_count: int):
    """Expanding, non-random blocks with h-session embargo AFTER last train label."""
    for start in range(INITIAL_TRAIN_SESSIONS, session_count, TEST_BLOCK_SESSIONS):
        end = min(start + TEST_BLOCK_SESSIONS, session_count)
        train = samples.loc[samples["target_idx"] < start - horizon].copy()
        test = samples.loc[
            (samples["origin_idx"] >= start) & (samples["origin_idx"] < end)
        ].copy()
        if train.empty or test.empty:
            continue
        if train["target_idx"].max() + horizon >= test["origin_idx"].min():
            raise ValueError("Train labels are not embargoed from test origins.")
        if train["date"].max() >= test["date"].min():
            raise ValueError("Walk-forward fold is not chronological.")
        yield start, train, test


def empirical_models(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    counts = np.array([
        [int(((train["origin_state"] == origin) & (train["target_state"] == destination)).sum())
         for destination in STATES]
        for origin in STATES
    ], dtype=float)
    if (counts.sum(axis=1) == 0).any() or (counts.sum(axis=0) == 0).any():
        raise ValueError("Training has insufficient observed transitions for all three states.")
    index = np.array([STATES.index(value) for value in test["origin_state"]])
    return {
        "persistence": np.eye(3)[index],
        "unconditional": np.tile(counts.sum(axis=0) / counts.sum(), (len(test), 1)),
        "markov": (counts / counts.sum(axis=1, keepdims=True))[index],
    }


def design_matrix(frame: pd.DataFrame, means: np.ndarray, scales: np.ndarray) -> np.ndarray:
    current = frame["origin_state"]
    observed = frame.loc[:, list(FEATURES)].to_numpy(dtype=float)
    if not np.isfinite(observed).all():
        raise ValueError("The predeclared feature set is incomplete.")
    return np.column_stack([
        np.ones(len(frame)),
        current.eq("RISK-ON").to_numpy(dtype=float),
        current.eq("NEUTRAL").to_numpy(dtype=float),
        (observed - means) / scales,
    ])


def fit_logistic(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, dict]:
    """Fixed-L2 multinomial logits, DE-RISK reference; train-only standardization."""
    raw = train.loc[:, list(FEATURES)].to_numpy(dtype=float)
    means = raw.mean(axis=0)
    scales = raw.std(axis=0)
    scales[scales == 0] = 1.0
    x = design_matrix(train, means, scales)
    xt = design_matrix(test, means, scales)
    y = np.array([STATES.index(value) for value in train["target_state"]])
    penalty = np.ones((x.shape[1], 2))
    penalty[0] = 0  # do not penalize intercepts

    def objective(flat):
        coef = flat.reshape(x.shape[1], 2)
        logits = np.column_stack([x @ coef, np.zeros(len(x))])
        probs = np.exp(logits - logsumexp(logits, axis=1, keepdims=True))
        loss = (logsumexp(logits, axis=1) - logits[np.arange(len(y)), y]).mean()
        loss += LOGISTIC_L2 / (2 * len(y)) * np.sum((coef * penalty) ** 2)
        residual = probs[:, :2] - np.eye(3)[y, :2]
        gradient = x.T @ residual / len(y) + LOGISTIC_L2 / len(y) * coef * penalty
        return float(loss), gradient.ravel()

    fitted = minimize(objective, np.zeros(x.shape[1] * 2),
                      method="L-BFGS-B", jac=True, options={"maxiter": 300, "ftol": 1e-11})
    if not fitted.success:
        raise RuntimeError(f"Fixed logistic fit did not converge: {fitted.message}")
    coefficients = fitted.x.reshape(x.shape[1], 2)
    logits = np.column_stack([xt @ coefficients, np.zeros(len(xt))])
    probabilities = np.exp(logits - logsumexp(logits, axis=1, keepdims=True))
    return probabilities, {
        "features": ["intercept", "current_RISK-ON", "current_NEUTRAL",
                     "body_stress_score_per_train_sd", "overall_stress_score_per_train_sd"],
        "destination_logits_vs_DE-RISK": {
            state: dict(zip(["intercept", "current_RISK-ON", "current_NEUTRAL",
                             "body_stress_score_per_train_sd", "overall_stress_score_per_train_sd"],
                            coefficients[:, j].tolist()))
            for j, state in enumerate(STATES[:2])
        },
        "train_factor_means": dict(zip(FEATURES, means.tolist())),
        "train_factor_scales": dict(zip(FEATURES, scales.tolist())),
        "l2_strength": LOGISTIC_L2,
    }


def run_replay(reconstructed: pd.DataFrame, canonical: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    records = []
    final_coefficients = {}
    published = canonical.loc[canonical["date"] <= pd.Timestamp(reconstructed["date"].iloc[-1])]
    for horizon in HORIZONS:
        samples = build_samples(reconstructed, canonical, horizon)
        if samples.empty:
            raise ValueError(f"No real-data pairs for {horizon} sessions.")
        for fold_start, train, test in walk_forward_folds(samples, horizon, len(published)):
            estimates = empirical_models(train, test)
            estimates["logistic"], coefficients = fit_logistic(train, test)
            final_coefficients[str(horizon)] = coefficients  # last training-only fit for disclosure
            for model in MODELS:
                scores = estimates[model]
                if not np.isfinite(scores).all() or (scores < 0).any() or not np.allclose(
                    scores.sum(axis=1), 1.0, atol=1e-10,
                ):
                    raise ValueError(f"{model} produced invalid normalized transition scores.")
                for item, values in zip(test.itertuples(index=False), scores):
                    records.append({
                        "horizon": horizon, "model": model, "fold_start_idx": fold_start,
                        "date": item.date, "target_date": item.target_date,
                        "origin_idx": item.origin_idx, "target_idx": item.target_idx,
                        "origin_state": item.origin_state, "target_state": item.target_state,
                        "origin_available_at_utc": item.origin_available_at_utc,
                        **{f"score_{state.lower().replace('-', '_')}": float(values[j])
                           for j, state in enumerate(STATES)},
                    })
    predictions = pd.DataFrame(records)
    for horizon in HORIZONS:
        group = predictions.loc[predictions["horizon"] == horizon]
        common = group.loc[group["model"] == MODELS[0], "date"].tolist()
        if not common or any(
            group.loc[group["model"] == model, "date"].tolist() != common for model in MODELS[1:]
        ):
            raise ValueError("Benchmarks do not share identical OOS observations.")
    return predictions, final_coefficients


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(source: Path, destination: Path) -> dict:
    """Persist separate, content-checked research artifacts; never touch the signal."""
    from src.regime_outlook_report import make_report, markdown_report

    bundle = load_verified_real_signal(source)
    signal_dir = source / "snapshots" / bundle.signal_snapshot_id
    input_dir = source / "daily_data" / "snapshots" / bundle.latest["data_snapshot_id"]
    reconstructed, canonical = rebuild_states(bundle, signal_dir)
    scored_full = score_daily_regimes(canonical)
    proof = prove_prefix_invariance(canonical, scored_full)
    predictions, coefficients = run_replay(reconstructed, canonical)
    report = make_report(
        predictions, reconstructed, coefficients, proof,
        bundle.latest["data_snapshot_id"], bundle.signal_snapshot_id,
    )
    destination.mkdir(parents=True, exist_ok=True)
    final = destination / bundle.signal_snapshot_id
    with tempfile.TemporaryDirectory(prefix=".regime-outlook-", dir=destination) as staging_name:
        staging = Path(staging_name)
        reconstructed.to_csv(staging / "reconstructed_states.csv", index=False,
                             float_format="%.17g", lineterminator="\n")
        predictions.to_csv(staging / "oos_predictions.csv", index=False,
                           float_format="%.17g", lineterminator="\n")
        (staging / "report.json").write_text(
            json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )
        (staging / "report.md").write_text(markdown_report(report))
        manifest = {
            "status": "RESEARCH RECONSTRUCTION / SHADOW ONLY",
            "signal_snapshot_id": bundle.signal_snapshot_id,
            "input_snapshot_id": bundle.latest["data_snapshot_id"],
            "source_signal_sha256": sha256(signal_dir / "signal_history.csv"),
            "source_canonical_sha256": sha256(input_dir / "canonical_daily.csv"),
            "files": {name: sha256(staging / name)
                      for name in ("reconstructed_states.csv", "oos_predictions.csv",
                                   "report.json", "report.md")},
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n"
        )
        if final.exists():
            prior = json.loads((final / "manifest.json").read_text())
            if any(prior[key] != manifest[key] for key in (
                "signal_snapshot_id", "input_snapshot_id",
                "source_signal_sha256", "source_canonical_sha256",
            )):
                raise ValueError("Existing research replay sources differ; refusing overwrite.")
            # A changed research report (not a published signal) may be regenerated
            # from the same verified source. Write its checksum manifest last; readers
            # fail closed if they arrive during replacement.
            for name in manifest["files"]:
                if sha256(final / name) != manifest["files"][name]:
                    os.replace(staging / name, final / name)
            os.replace(staging / "manifest.json", final / "manifest.json")
        else:
            os.replace(staging, final)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Frozen-v1 Yahoo transition research replay.")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1]
                        / "data" / "free_signal")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]
                        / "research" / "regime_outlook")
    options = parser.parse_args()
    result = generate(options.source, options.output)
    print(json.dumps({
        "signal_snapshot_id": result["signal_snapshot_id"],
        "recommendations": {h: item["recommendation"]
                            for h, item in result["horizons"].items()},
    }, indent=2))