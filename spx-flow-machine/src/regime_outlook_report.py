"""Predeclared OOS desk gate and human-readable research-only report."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.regime_outlook_lab import (
    ALARM_LEVEL, CALIBRATION_BINS, HORIZONS, MODELS, SCORE_FLOOR, STATES,
)

SCORE_COLUMNS = ("score_risk_on", "score_neutral", "score_de_risk")
MIN_OOS_ORIGINS = 1500
MIN_DISTINCT_ENTRIES_PER_STATE = 50
MIN_FOLDS = 6
MIN_RELATIVE_GAIN = 0.01
MIN_FOLD_WIN_SHARE = 2 / 3
MAX_ECE = 0.05
MAX_BIN_GAP = 0.10
MIN_BIN_SIZE = 30
MIN_CLASS_POSITIVES = 50


def loss_vectors(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    observed = np.array([STATES.index(state) for state in frame["target_state"]])
    scores = frame.loc[:, list(SCORE_COLUMNS)].to_numpy(dtype=float)
    if (not np.isfinite(scores).all() or (scores < 0).any()
            or not np.allclose(scores.sum(axis=1), 1, atol=1e-10)):
        raise ValueError("Normalized three-state OOS scores are required.")
    # Clipping is ONLY for evaluating log loss. Raw persistence remains one-hot.
    clipped = np.clip(scores, SCORE_FLOOR, 1)
    clipped /= clipped.sum(axis=1, keepdims=True)
    logloss = -np.log(clipped[np.arange(len(frame)), observed])
    brier = np.sum((scores - np.eye(3)[observed]) ** 2, axis=1)
    return logloss, brier


def reliability(frame: pd.DataFrame) -> dict:
    scores = frame.loc[:, list(SCORE_COLUMNS)].to_numpy(dtype=float)
    observed = frame["target_state"].to_numpy()
    result = {}
    for j, state in enumerate(STATES):
        probability = scores[:, j]
        actual = (observed == state).astype(float)
        bins = np.clip(np.digitize(probability, CALIBRATION_BINS, right=False) - 1, 0, 4)
        entries = [
            {
                "range": f"{CALIBRATION_BINS[k]:.1f}–{CALIBRATION_BINS[k + 1]:.1f}",
                "n": int((bins == k).sum()),
                "mean_score": float(probability[bins == k].mean()) if (bins == k).any() else None,
                "observed_rate": float(actual[bins == k].mean()) if (bins == k).any() else None,
            }
            for k in range(5)
        ]
        populated = [entry for entry in entries if entry["n"]]
        ece = sum(
            entry["n"] * abs(entry["mean_score"] - entry["observed_rate"])
            for entry in populated
        ) / len(frame)
        max_gap = max(abs(entry["mean_score"] - entry["observed_rate"])
                      for entry in populated)
        result[state] = {
            "positives": int(actual.sum()), "ece": float(ece),
            "max_bin_gap": float(max_gap), "bins": entries,
            "passes": (
                actual.sum() >= MIN_CLASS_POSITIVES
                and all(entry["n"] >= MIN_BIN_SIZE for entry in populated)
                and ece <= MAX_ECE and max_gap <= MAX_BIN_GAP
            ),
        }
    return result


def transition_counts(reconstructed: pd.DataFrame, common: pd.DataFrame) -> dict:
    paired = pd.crosstab(
        pd.Categorical(common["origin_state"], categories=STATES),
        pd.Categorical(common["target_state"], categories=STATES),
        dropna=False,
    )
    # Distinct adjacent-state changes, not inflated counts of overlapping h labels.
    states = reconstructed.loc[:, ["date", "risk_signal"]].copy()
    states["changed"] = states["risk_signal"].ne(states["risk_signal"].shift())
    states = states.loc[
        (states["date"] >= common["target_date"].min())
        & (states["date"] <= common["target_date"].max())
    ]
    entered = states.loc[states["changed"]]
    entries = {state: int(entered["risk_signal"].eq(state).sum()) for state in STATES}
    return {
        "origin_class_counts": {state: int(common["origin_state"].eq(state).sum()) for state in STATES},
        "destination_class_counts": {state: int(common["target_state"].eq(state).sum()) for state in STATES},
        "h_step_transition_counts": {
            state: {target: int(paired.loc[state, target]) for target in STATES}
            for state in STATES
        },
        "distinct_one_step_entries_by_destination": entries,
        "distinct_one_step_changes": sum(entries.values()),
    }


def summarize_model(frame: pd.DataFrame) -> dict:
    logs, briers = loss_vectors(frame)
    scores = frame.loc[:, list(SCORE_COLUMNS)].to_numpy(dtype=float)
    confusion = pd.crosstab(
        pd.Categorical(frame["target_state"], categories=STATES),
        pd.Categorical([STATES[j] for j in scores.argmax(axis=1)], categories=STATES),
        dropna=False,
    )
    calib = reliability(frame)
    return {
        "n": len(frame),
        "log_loss": float(logs.mean()),
        "multiclass_brier": float(briers.mean()),
        "mean_max_score": float(scores.max(axis=1).mean()),
        "destination_score_std": dict(zip(STATES, scores.std(axis=0).tolist())),
        "calibration": calib,
        "calibration_pass": all(value["passes"] for value in calib.values()),
        "confusion_actual_rows_predicted_columns": {
            state: {target: int(confusion.loc[state, target]) for target in STATES}
            for state in STATES
        },
    }


def paired_comparison(challenger: pd.DataFrame, baseline: pd.DataFrame) -> dict:
    if (challenger["date"].tolist() != baseline["date"].tolist()
            or challenger["target_state"].tolist() != baseline["target_state"].tolist()):
        raise ValueError("Benchmarks must use identical OOS observations in the same order.")
    cl, cb = loss_vectors(challenger)
    bl, bb = loss_vectors(baseline)
    fold = challenger["fold_start_idx"].to_numpy()
    nfold = len(np.unique(fold))
    wins = int(sum(
        cl[fold == value].mean() < bl[fold == value].mean()
        and cb[fold == value].mean() < bb[fold == value].mean()
        for value in np.unique(fold)
    ))
    eras = []
    for name, indexes in zip(("early", "middle", "late"),
                             np.array_split(np.arange(len(cl)), 3)):
        eras.append({
            "era": name,
            "first": challenger.iloc[indexes[0]]["date"],
            "last": challenger.iloc[indexes[-1]]["date"],
            "n": len(indexes),
            "log_loss_delta": float(bl[indexes].mean() - cl[indexes].mean()),
            "brier_delta": float(bb[indexes].mean() - cb[indexes].mean()),
        })
    rel_log = float((bl.mean() - cl.mean()) / bl.mean())
    rel_brier = float((bb.mean() - cb.mean()) / bb.mean())
    return {
        "relative_log_loss_gain": rel_log,
        "relative_brier_gain": rel_brier,
        "annual_fold_dual_metric_wins": wins,
        "annual_fold_count": nfold,
        "chronological_thirds": eras,
        "passes_stability_and_gain": (
            rel_log >= MIN_RELATIVE_GAIN and rel_brier >= MIN_RELATIVE_GAIN
            and nfold >= MIN_FOLDS and wins / nfold >= MIN_FOLD_WIN_SHARE
            and all(era["log_loss_delta"] > 0 and era["brier_delta"] > 0 for era in eras)
        ),
    }


def lead_behavior(predictions: pd.DataFrame, reconstructed: pd.DataFrame, model: str) -> dict:
    """Horizon-matched, unique DE-RISK entry dates with all three OOS lead scores."""
    states = reconstructed["risk_signal"].tolist()
    dates = reconstructed["date"].tolist()
    entries = [
        dates[i] for i in range(1, len(states))
        if states[i] == "DE-RISK" and states[i - 1] != "DE-RISK"
    ]
    per_horizon = {
        h: predictions.loc[
            (predictions["horizon"] == h) & (predictions["model"] == model)
            & (predictions["target_state"] == "DE-RISK")
        ].set_index("target_date")
        for h in HORIZONS
    }
    matched = [
        date for date in entries
        if all(date in per_horizon[h].index for h in HORIZONS)
    ]
    medians = {}
    for h in HORIZONS:
        values = per_horizon[h].loc[matched, "score_de_risk"] if matched else []
        medians[f"minus_{h}"] = float(np.median(values)) if matched else None
    false_alarms = {}
    for h in HORIZONS:
        frame = predictions.loc[
            (predictions["horizon"] == h) & (predictions["model"] == model)
        ].sort_values("origin_idx").copy()
        consecutive = frame["origin_idx"].diff().eq(1)
        rises = frame.loc[
            consecutive & frame["origin_state"].ne("DE-RISK")
            & frame["score_de_risk"].gt(frame["score_de_risk"].shift())
        ]
        alerts = frame.loc[
            frame["origin_state"].ne("DE-RISK") & frame["score_de_risk"].ge(ALARM_LEVEL)
        ]
        false = alerts["target_state"].ne("DE-RISK")
        false_alarms[str(h)] = {
            "threshold": ALARM_LEVEL, "alerts": len(alerts), "false_alarms": int(false.sum()),
            "false_alarm_fraction": float(false.mean()) if len(alerts) else None,
            "rising_score_origins": len(rises),
            "rising_score_without_de_risk_destination": int(
                rises["target_state"].ne("DE-RISK").sum()
            ),
        }
    return {
        "matched_distinct_de_risk_entries": len(matched),
        "median_de_risk_score_prior_sessions": medians,
        "false_alarms": false_alarms,
    }


def make_report(predictions: pd.DataFrame, reconstructed: pd.DataFrame, coefficients: dict,
                prefix_checks: list[dict], input_id: str, signal_id: str) -> dict:
    output = {
        "status": "RESEARCH / SHADOW — NOT VALIDATED / NOT FOR PORTFOLIO ACTION",
        "input_snapshot_id": input_id,
        "signal_snapshot_id": signal_id,
        "model_version": "free_daily_regime_v1 (unchanged)",
        "target": "frozen current-state regime at t+h, NOT forward SPX return",
        "data_policy": (
            "Yahoo historical daily closes were retrieved in one later snapshot. "
            "Frozen-v1 features and states use only observations dated <= t, but past "
            "Yahoo vintages are NOT available. These are date-ordered retrospective OOS "
            "research replays, NOT historical live predictions or deployable probabilities."
        ),
        "design": {
            "protocol_status": (
                "Rules are fixed in this implementation for reproducible replay, "
                "but no independently dated preregistration exists. Treat findings as exploratory."
            ),
            "horizons_trading_sessions": list(HORIZONS),
            "training": "expanding, initial 1260 canonical sessions; tests in 252-session blocks",
            "embargo": "last training target index < first test origin index - horizon",
            "factors": ["current regime", *("body stress", "overall stress")],
            "logistic": "3-class, fixed L2=10, train-only scaling; DE-RISK reference",
            "markov": "direct empirical h-step conditional frequencies from training labels only",
            "unconditional": "empirical training-target frequencies only",
            "persistence": "one-hot current regime; scoring-only floor 1e-6 for log loss",
            "hidden_model": (
                "NOT RUN: without historical source vintages, a latent switching model's "
                "state identifiability and fair point-in-time comparison cannot be established. "
                "No likelihood-based selection or hyperparameter search."
            ),
            "calibration_gate": (
                "For every destination: >=50 positives, every populated one-of-five fixed-width "
                "score bins >=30 observations, ECE <=0.05 and max bin gap <=0.10."
            ),
            "sample_gate": ">=1500 common OOS origins, >=6 test blocks, >=50 distinct one-step entries per destination",
            "improvement_gate": (
                "Log loss AND multiclass Brier >=1% better than BOTH persistence and "
                "state-conditional Markov on identical rows; dual-metric wins in >=2/3 "
                "of annual blocks and positive gains in all three chronological thirds."
            ),
            "provenance_gate": "archived, dated Yahoo vintages available BEFORE each forecast origin",
        },
        "prefix_invariance_real_data_checks": prefix_checks,
        "reconstruction": {
            "rows": len(reconstructed), "first": reconstructed.iloc[0]["date"],
            "last": reconstructed.iloc[-1]["date"],
            "research_status": "RESEARCH RECONSTRUCTION",
            "source_vintage_gate_pass": False,
        },
        "horizons": {},
    }
    for h in HORIZONS:
        grouped = {
            model: predictions.loc[
                (predictions["horizon"] == h) & (predictions["model"] == model)
            ].sort_values("date").reset_index(drop=True)
            for model in MODELS
        }
        common = grouped["markov"]
        counts = transition_counts(reconstructed, common)
        sample_pass = (
            len(common) >= MIN_OOS_ORIGINS
            and common["fold_start_idx"].nunique() >= MIN_FOLDS
            and all(n >= MIN_DISTINCT_ENTRIES_PER_STATE
                    for n in counts["distinct_one_step_entries_by_destination"].values())
        )
        metrics = {model: summarize_model(grouped[model]) for model in MODELS}
        compared = {
            model: {
                baseline: paired_comparison(grouped[model], grouped[baseline])
                for baseline in ("persistence", "markov") if model != baseline
            }
            for model in ("unconditional", "logistic")
        }
        markov_vs_persistence = paired_comparison(grouped["markov"], grouped["persistence"])
        logistic_pass = (
            sample_pass and metrics["logistic"]["calibration_pass"]
            and all(c["passes_stability_and_gain"] for c in compared["logistic"].values())
        )
        output["horizons"][str(h)] = {
            "n_common_oos_origins": len(common),
            "first_oos_origin": common.iloc[0]["date"],
            "last_oos_origin": common.iloc[-1]["date"],
            "folds": int(common["fold_start_idx"].nunique()),
            "counts": counts,
            "sample_gate_pass": bool(sample_pass),
            "metrics": metrics,
            "paired_comparisons": compared,
            "markov_vs_persistence": markov_vs_persistence,
            "last_fold_logistic_coefficients_diagnostic_only": coefficients[str(h)],
            "lead_behavior": {
                model: lead_behavior(predictions, reconstructed, model)
                for model in ("markov", "logistic")
            },
            "quantitative_logistic_gate_pass": bool(logistic_pass),
            "recommendation": "INSUFFICIENT EVIDENCE",
            "recommendation_reason": (
                "Historical Yahoo source vintages were not captured at each session: "
                "real-time point-in-time availability cannot be certified. "
                + ("Quantitative logistic gates also fail." if not logistic_pass
                   else "Quantitative gates alone cannot override the provenance gate.")
            ),
        }
    return output


def markdown_report(report: dict) -> str:
    lines = [
        "# Regime Outlook — RESEARCH / SHADOW",
        "",
        "**NOT VALIDATED / NOT FOR PORTFOLIO ACTION.** No top-card action, "
        "classifier threshold, or live forecast is changed.",
        "",
        "## Data contract and predeclared gate",
        report["data_policy"], "",
        f"Frozen v1 reconstruction: {report['reconstruction']['rows']:,} rows, "
        f"{report['reconstruction']['first']}–{report['reconstruction']['last']}; "
        "marked RESEARCH RECONSTRUCTION. Prefix invariance on actual Yahoo data: "
        + ", ".join(str(v["prefix_rows"]) for v in report["prefix_invariance_real_data_checks"])
        + " rows, zero changes to past states/scores.",
        "",
        "Origins use only the two predeclared causal scores and current state at t. "
        "Targets are the frozen classifier's state exactly h observed trading sessions "
        "later, not SPX returns. Gaps in SPX observations invalidate a pair. "
        "The origin's recorded availability is the maximum of close+6h, Yahoo "
        "retrieval, and reconstruction calculation. Because historical rows were "
        "obtained in the later Yahoo snapshot, **this cannot certify a forecast "
        "was available at its original historical date**.",
        "",
        "Expanding 1,260-session initial training window, 252-session test blocks, "
        "and horizon-sized embargo *after the last training label*. Models and "
        "thresholds were declared before inspecting results: persistence, "
        "unconditional frequencies, direct state-conditional empirical Markov, "
        "and fixed-L2 multinomial logistic on current state plus body and overall "
        "stress. No search or crisis-era tuning. These rules are fixed in this "
        "implementation but were not independently preregistered; interpret the "
        "quantitative comparisons as exploratory. A hidden-state challenger was not "
        "run: a fair identifiable point-in-time comparison cannot be established "
        "from these historical source vintages.",
        "",
        "Calibration gate: " + report["design"]["calibration_gate"],
        "Promotion requires: " + report["design"]["sample_gate"] + "; "
        + report["design"]["improvement_gate"] + "; "
        + report["design"]["provenance_gate"] + ".",
        "The persistence benchmark remains exactly one-hot; only its log-loss "
        "evaluation clips to 1e-6. No raw transition score is promoted to a "
        "production probability. Overlapping h-day targets are reported with "
        "distinct one-step transition counts and fold/era checks, not treated "
        "as independent events.",
        "",
    ]
    for h in HORIZONS:
        item = report["horizons"][str(h)]
        counts = item["counts"]
        lines.extend([
            f"## {h} trading day{'s' if h > 1 else ''}: {item['recommendation']}",
            item["recommendation_reason"],
            f"Common chronological OOS origins: {item['n_common_oos_origins']:,} "
            f"({item['first_oos_origin']}–{item['last_oos_origin']}); "
            f"{item['folds']} test blocks. Distinct adjacent state changes: "
            f"{counts['distinct_one_step_changes']} "
            f"(destination entries: {counts['distinct_one_step_entries_by_destination']}).",
            f"Origin classes: {counts['origin_class_counts']}; destination classes: "
            f"{counts['destination_class_counts']}. "
            f"Observed h-step transition counts: {counts['h_step_transition_counts']}.",
            f"Sample gate: {'PASS' if item['sample_gate_pass'] else 'FAIL'}; "
            f"logistic quantitative gate: {'PASS' if item['quantitative_logistic_gate_pass'] else 'FAIL'}; "
            "historical source-vintage gate: FAIL.",
            "",
            "| Model | OOS log loss ↓ | Multiclass Brier ↓ | Mean max score | Calibration |",
            "|---|---:|---:|---:|---|",
        ])
        for model in MODELS:
            m = item["metrics"][model]
            lines.append(
                f"| {model} | {m['log_loss']:.4f} | {m['multiclass_brier']:.4f} | "
                f"{m['mean_max_score']:.3f} | {'PASS' if m['calibration_pass'] else 'FAIL'} |"
            )
        lines.extend(["", "Pairwise gains versus common-row baselines "
                      "(positive = lower log loss AND Brier):"])
        for candidate in ("markov", "logistic"):
            comparisons = ({"persistence": item["markov_vs_persistence"]}
                           if candidate == "markov" else item["paired_comparisons"]["logistic"])
            for baseline, result in comparisons.items():
                lines.append(
                    f"- {candidate} vs {baseline}: log-loss {result['relative_log_loss_gain']:+.2%}, "
                    f"Brier {result['relative_brier_gain']:+.2%}; "
                    f"{result['annual_fold_dual_metric_wins']}/{result['annual_fold_count']} "
                    "blocks win both; chronological third deltas (log loss / Brier): "
                    + "; ".join(f"{e['era']} {e['log_loss_delta']:+.4f}/{e['brier_delta']:+.4f}"
                                for e in result["chronological_thirds"]) + "."
                )
        lines.extend(["", "Classwise reliability (fixed 0.2-wide score bins; "
                      "each bin lists n / mean score / observed destination rate):"])
        for model in MODELS:
            lines.append(f"- **{model}:**")
            for state, r in item["metrics"][model]["calibration"].items():
                bins = "; ".join(
                    f"{b['range']}: {b['n']} / {b['mean_score']:.3f} / {b['observed_rate']:.3f}"
                    for b in r["bins"] if b["n"]
                )
                lines.append(
                    f"  - {state} ({r['positives']} positives): ECE {r['ece']:.3f}, "
                    f"max gap {r['max_bin_gap']:.3f}; {bins}."
                )
        lines.extend(["", "Secondary diagnostics: confusion matrices (actual rows → predicted columns) "
                      "and score sharpness (destination score standard deviations):"])
        for model in MODELS:
            m = item["metrics"][model]
            lines.append(
                f"- {model}: confusion {m['confusion_actual_rows_predicted_columns']}; "
                f"sharpness {m['destination_score_std']}."
            )
        lines.extend(["", "DE-RISK entry lead behavior on *distinct* entry dates "
                      "with matching 1/3/5-session OOS scores (not a trade alarm):"])
        for model, entry in item["lead_behavior"].items():
            alarm = entry["false_alarms"][str(h)]
            lines.append(
                f"- {model}: matched entries {entry['matched_distinct_de_risk_entries']}; "
                f"median matched DE-RISK score at −5/−3/−1: "
                f"{entry['median_de_risk_score_prior_sessions']}; "
                f"{h}D rising-score non-DE-RISK origins without DE-RISK destination: "
                f"{alarm['rising_score_without_de_risk_destination']}/"
                f"{alarm['rising_score_origins']}; "
                f"{h}D false alarms at >=0.50 from a non-DE-RISK origin: "
                f"{alarm['false_alarms']}/{alarm['alerts']} "
                f"(fraction {alarm['false_alarm_fraction']})."
            )
        lines.extend([
            "", "Last training fold's regularized logit coefficients "
            "(RISK-ON/NEUTRAL relative to DE-RISK; descriptive, not production parameters):",
            "```json",
            json.dumps(item["last_fold_logistic_coefficients_diagnostic_only"],
                       indent=2, sort_keys=True),
            "```", "",
        ])
    lines += [
        "## Decision",
        "**INSUFFICIENT EVIDENCE at 1D, 3D, and 5D.** No model is selected or "
        "promoted. The frozen current-state PM action remains authoritative. "
        "No Signal Hub connection, actionable outlook, or new source was added.",
    ]
    return "\n".join(lines) + "\n"