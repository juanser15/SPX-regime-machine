"""Binary event diagnostics and fixed, conservative shadow promotion gates."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from src.regime_outlook_lab import HORIZONS
from src.transition_hazard_lab import MODELS, TARGETS, SENSITIVITY_CUTOFFS

MIN_ORIGINS = 1000
MIN_POSITIVES = 100
MIN_NEGATIVES = 500
MIN_UNIQUE_EVENTS = 50
MIN_FOLDS = 6
MIN_RELATIVE_GAIN = 0.01
MIN_DUAL_FOLD_WIN_SHARE = 2 / 3
MAX_ECE = 0.05
MAX_BIN_GAP = 0.10
MIN_POPULATED_BIN = 30
# Operating criteria are fixed before inspecting the new transition results.
MIN_ENTRY_ALERT_RECALL = 0.25
MIN_ENTRY_PRECISION_LIFT = 2.0
MAX_ENTRY_FPR = 0.15


def losses(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    y = frame["event"].to_numpy(dtype=int)
    p = frame["score"].to_numpy(dtype=float)
    if (not np.isfinite(p).all() or (p < 0).any() or (p > 1).any()):
        raise ValueError("Binary scores must be finite within [0,1].")
    clipped = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(clipped) + (1 - y) * np.log1p(-clipped)), (p - y) ** 2


def average_precision(y: np.ndarray, p: np.ndarray) -> float | None:
    positives = int(y.sum())
    if not positives:
        return None
    order = np.argsort(-p, kind="mergesort")
    ranked_y, ranked_p = y[order], p[order]
    ends = np.r_[np.flatnonzero(ranked_p[1:] != ranked_p[:-1]) + 1, len(y)]
    previous = 0
    total = 0.0
    cumulative = np.cumsum(ranked_y)
    for end in ends:
        group_positives = cumulative[end - 1] - (cumulative[previous - 1] if previous else 0)
        total += group_positives * (cumulative[end - 1] / end)
        previous = end
    return float(total / positives)


def auc(y: np.ndarray, p: np.ndarray) -> float | None:
    positives = int(y.sum())
    negatives = len(y) - positives
    if not positives or not negatives:
        return None
    return float((rankdata(p)[y == 1].sum() - positives * (positives + 1) / 2)
                 / (positives * negatives))


def calibration(frame: pd.DataFrame) -> dict:
    y = frame["event"].to_numpy(dtype=float)
    p = frame["score"].to_numpy(dtype=float)
    bins = np.minimum((p * 5).astype(int), 4)
    detail = []
    for k in range(5):
        mask = bins == k
        detail.append({
            "bin": f"{k / 5:.1f}–{(k + 1) / 5:.1f}",
            "n": int(mask.sum()),
            "mean_score": float(p[mask].mean()) if mask.any() else None,
            "event_rate": float(y[mask].mean()) if mask.any() else None,
        })
    populated = [v for v in detail if v["n"]]
    gaps = [abs(v["mean_score"] - v["event_rate"]) for v in populated]
    ece = sum(v["n"] * gap for v, gap in zip(populated, gaps)) / len(frame)
    maximum = max(gaps)
    return {
        "ece": float(ece), "max_bin_gap": float(maximum),
        "bins": detail,
        "pass": bool(all(v["n"] >= MIN_POPULATED_BIN for v in populated)
                     and ece <= MAX_ECE and maximum <= MAX_BIN_GAP),
    }


def model_metrics(frame: pd.DataFrame) -> dict:
    ll, br = losses(frame)
    y, p = frame["event"].to_numpy(dtype=int), frame["score"].to_numpy(dtype=float)
    return {
        "n": len(frame), "events": int(y.sum()),
        "log_loss": float(ll.mean()), "brier": float(br.mean()),
        "average_precision": average_precision(y, p),
        "roc_auc_secondary": auc(y, p),
        "mean_score": float(p.mean()), "score_std": float(p.std()),
        "calibration": calibration(frame),
    }


def compare(market: pd.DataFrame, baseline: pd.DataFrame) -> dict:
    if (market["date"].tolist() != baseline["date"].tolist()
            or market["event"].tolist() != baseline["event"].tolist()):
        raise ValueError("Models must score identical chronological OOS risk sets.")
    ml, mb = losses(market)
    bl, bb = losses(baseline)
    folds = market["fold_start_idx"].to_numpy()
    unique = np.unique(folds)
    wins = int(sum(
        ml[folds == value].mean() < bl[folds == value].mean()
        and mb[folds == value].mean() < bb[folds == value].mean()
        for value in unique
    ))
    eras = []
    for name, ids in zip(("early", "middle", "late"),
                         np.array_split(np.arange(len(market)), 3)):
        eras.append({
            "era": name, "n": len(ids),
            "first": market.iloc[ids[0]]["date"],
            "last": market.iloc[ids[-1]]["date"],
            "log_loss_delta": float(bl[ids].mean() - ml[ids].mean()),
            "brier_delta": float(bb[ids].mean() - mb[ids].mean()),
        })
    gain_ll = float((bl.mean() - ml.mean()) / bl.mean())
    gain_br = float((bb.mean() - mb.mean()) / bb.mean())
    return {
        "relative_log_loss_gain": gain_ll,
        "relative_brier_gain": gain_br,
        "dual_metric_fold_wins": wins,
        "folds": len(unique),
        "chronological_thirds": eras,
        "pass": bool(
            gain_ll >= MIN_RELATIVE_GAIN and gain_br >= MIN_RELATIVE_GAIN
            and len(unique) >= MIN_FOLDS and wins / len(unique) >= MIN_DUAL_FOLD_WIN_SHARE
            and all(e["log_loss_delta"] > 0 and e["brier_delta"] > 0 for e in eras)
        ),
    }


def operating_point(frame: pd.DataFrame) -> dict:
    y = frame["event"].to_numpy(dtype=bool)
    threshold = frame["train_top_decile_threshold"].to_numpy(dtype=float)
    alert = frame["score"].to_numpy(dtype=float) >= threshold
    tp, fp = int((alert & y).sum()), int((alert & ~y).sum())
    positives, negatives = int(y.sum()), int((~y).sum())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / positives if positives else None
    fpr = fp / negatives if negatives else None
    prevalence = positives / len(y)
    return {
        "policy": "fold-specific 90th percentile of fitted TRAIN scores, never tuned on OOS",
        "alerts": tp + fp, "true_alarms": tp, "false_alarms": fp,
        "precision": precision, "recall": recall, "false_positive_rate": fpr,
        "base_event_rate": prevalence,
        "precision_lift": precision / prevalence if precision is not None and prevalence else None,
    }


def lead_table(entry_predictions: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    records = []
    for h in HORIZONS:
        group = entry_predictions.loc[
            (entry_predictions["target"] == "de_risk_entry")
            & (entry_predictions["horizon"] == h)
            & (entry_predictions["model"] == "market")
        ]
        indexed = group.set_index("origin_idx")
        if indexed.empty:
            continue
        events = [
            i for i in range(1, len(states))
            if states.iloc[i]["risk_signal"] == "DE-RISK"
            and states.iloc[i - 1]["risk_signal"] != "DE-RISK"
            and states.iloc[i]["date"] >= group["date"].min()
            and states.iloc[i]["date"] <= group["target_date"].max()
        ]
        for event_idx in events:
            row = {"horizon": h, "entry_date": states.iloc[event_idx]["date"]}
            eligible = []
            for lag in range(5, 0, -1):
                origin = event_idx - lag
                if origin in indexed.index and states.iloc[origin]["risk_signal"] != "DE-RISK":
                    prediction = indexed.loc[origin]
                    score = float(prediction["score"])
                    row[f"score_minus_{lag}"] = score
                    if lag <= h and score >= prediction["train_top_decile_threshold"]:
                        eligible.append(lag)
                else:
                    row[f"score_minus_{lag}"] = None
            row["first_elevated_lead_sessions"] = max(eligible) if eligible else None
            row["matched_horizon_origin"] = bool(pd.notna(row[f"score_minus_{h}"]))
            records.append(row)
    return pd.DataFrame.from_records(records)


def sensitivity_summary(variants: dict[str, pd.DataFrame]) -> dict:
    output = {}
    for cutoff, predictions in variants.items():
        output[cutoff] = {}
        for h in HORIZONS:
            frames = {
                model: predictions.loc[
                    (predictions["horizon"] == h) & (predictions["model"] == model)
                ].sort_values("date").reset_index(drop=True)
                for model in MODELS
            }
            market, duration = frames["market"], frames["state_duration"]
            comparison = compare(market, duration)
            output[cutoff][str(h)] = {
                "oos_origins": len(market),
                "events": int(market["event"].sum()),
                "distinct_entry_dates": int(market.loc[market["event"] == 1, "first_event_date"].nunique()),
                "market_vs_duration": {
                    key: comparison[key] for key in (
                        "relative_log_loss_gain", "relative_brier_gain",
                        "dual_metric_fold_wins", "folds",
                    )
                },
                "same_positive_direction": bool(
                    comparison["relative_log_loss_gain"] > 0
                    and comparison["relative_brier_gain"] > 0
                ),
            }
    return output


def make_report(predictions: pd.DataFrame, states: pd.DataFrame,
                sensitivity: dict[str, pd.DataFrame], prefix: list[dict],
                signal_id: str, input_id: str) -> tuple[dict, pd.DataFrame]:
    leads = lead_table(predictions, states)
    sensitivity_results = sensitivity_summary(sensitivity)
    report = {
        "status": "RESEARCH / SHADOW — NOT VALIDATED / NOT FOR PORTFOLIO ACTION",
        "signal_snapshot_id": signal_id, "input_snapshot_id": input_id,
        "source_vintage_gate_pass": False,
        "data_policy": (
            "Frozen causal date-prefix reconstruction from real persisted Yahoo closes; "
            "historical vendor vintages were retrieved later. Retrospective chronological "
            "OOS, NOT an executable historical point-in-time forecast."
        ),
        "protocol": {
            "registration": "Fixed in code; no independently dated preregistration. Exploratory.",
            "targets": {
                "de_risk_entry": "non-DE-RISK origins; first DE-RISK observation in next h sessions",
                "any_transition": "all three origin states; S_(t+h) != S_t (endpoint, not any temporary round-trip)",
                "de_risk_exit": "DE-RISK origins; first non-DE-RISK observation in next h sessions",
            },
            "features": ["current state", "log1p(current run duration)",
                         "body_stress_score at t", "overall_stress_score at t"],
            "models": ["train-only Jeffreys-smoothed unconditional event rate",
                       "fixed-L2 state/duration logistic", "same fixed-L2 logistic plus two market scores"],
            "l2": 10, "initial_train_sessions": 1260, "test_block_sessions": 252,
            "purge": "last training label index < first test origin index - h",
            "operating_threshold": "fold-specific 90th percentile of fitted training scores; OOS untouched",
            "gate": (
                ">=1000 OOS origins, >=100 positive labels, >=500 negatives, >=50 distinct "
                "events, >=6 folds; >=1% lower BOTH log loss and Brier than BOTH baselines; "
                ">=2/3 dual-metric fold wins vs duration, positive gains in all thirds; "
                "five fixed-width bins each populated >=30, ECE <=0.05, max gap <=0.10. "
                "Entry additionally needs alert recall >=0.25, precision >=2x base rate "
                "and false-positive rate <=0.15. No PASS without historical source vintages."
            ),
            "sensitivity": "Only DE-RISK entry; frozen cutoff alternatives 30/70 and 40/60, not selected or tuned.",
        },
        "prefix_invariance_checks": prefix,
        "targets": {},
        "sensitivity_appendix": sensitivity_results,
    }
    for target in TARGETS:
        report["targets"][target] = {}
        for h in HORIZONS:
            frames = {
                model: predictions.loc[
                    (predictions["target"] == target)
                    & (predictions["horizon"] == h)
                    & (predictions["model"] == model)
                ].sort_values("date").reset_index(drop=True)
                for model in MODELS
            }
            common = frames["market"]
            count = int(common["event"].sum())
            unique_events = int(common.loc[common["event"] == 1, "first_event_date"].nunique())
            enough = bool(
                len(common) >= MIN_ORIGINS and count >= MIN_POSITIVES
                and len(common) - count >= MIN_NEGATIVES
                and unique_events >= MIN_UNIQUE_EVENTS
                and common["fold_start_idx"].nunique() >= MIN_FOLDS
            )
            metrics = {model: model_metrics(frame) for model, frame in frames.items()}
            comparisons = {
                model: compare(common, frames[model])
                for model in ("unconditional", "state_duration")
            }
            operating = operating_point(common)
            lead_group = leads.loc[leads["horizon"] == h] if target == "de_risk_entry" else pd.DataFrame()
            covered = lead_group.loc[lead_group["matched_horizon_origin"]] if not lead_group.empty else pd.DataFrame()
            detected = (covered["first_elevated_lead_sessions"].dropna()
                        if not covered.empty else pd.Series(dtype=float))
            lead = ({
                "distinct_entries_in_oos_range": len(lead_group),
                "matched_event_origins": len(covered),
                "entries_elevated_before_event": len(detected),
                "median_first_elevated_lead_sessions": (
                    float(detected.median()) if len(detected) else None
                ),
                "median_score_by_lag": {
                    f"minus_{k}": (
                        float(lead_group[f"score_minus_{k}"].median())
                        if lead_group[f"score_minus_{k}"].notna().any() else None
                    ) for k in range(5, 0, -1)
                },
                "lead_csv": "de_risk_entry_leads.csv",
            } if target == "de_risk_entry" else None)
            operational = True
            sensitivity_pass = True
            if target == "de_risk_entry":
                operational = bool(
                    operating["recall"] is not None and operating["recall"] >= MIN_ENTRY_ALERT_RECALL
                    and operating["precision_lift"] is not None
                    and operating["precision_lift"] >= MIN_ENTRY_PRECISION_LIFT
                    and operating["false_positive_rate"] is not None
                    and operating["false_positive_rate"] <= MAX_ENTRY_FPR
                    and lead["entries_elevated_before_event"] > 0
                )
                sensitivity_pass = all(
                    sensitivity_results[f"{low}/{high}"][str(h)]["same_positive_direction"]
                    and sensitivity_results[f"{low}/{high}"][str(h)]["distinct_entry_dates"] >= MIN_UNIQUE_EVENTS
                    for low, high in SENSITIVITY_CUTOFFS
                )
            quantitative = bool(enough and all(x["pass"] for x in comparisons.values())
                                and metrics["market"]["calibration"]["pass"]
                                and operational and sensitivity_pass)
            recommendation = ("INSUFFICIENT EVIDENCE" if not enough or quantitative
                              else "FAIL")
            report["targets"][target][str(h)] = {
                "risk_set": report["protocol"]["targets"][target],
                "first_oos_origin": common.iloc[0]["date"],
                "last_oos_origin": common.iloc[-1]["date"],
                "folds": int(common["fold_start_idx"].nunique()),
                "origins": len(common), "event_labels": count,
                "non_events": len(common) - count,
                "base_event_rate": count / len(common),
                "distinct_event_dates": unique_events,
                "effective_sample_note": (
                    "Distinct event dates are not independent OOS origins; h-session labels "
                    "overlap. No independence-based uncertainty interval is claimed."
                ),
                "origin_state_counts": common["origin_state"].value_counts().to_dict(),
                "metrics": metrics, "market_vs": comparisons,
                "market_operating_point": operating,
                "lead_behavior": lead,
                "sample_gate_pass": enough, "operating_gate_pass": operational,
                "sensitivity_gate_pass": sensitivity_pass if target == "de_risk_entry" else None,
                "quantitative_gate_pass": quantitative,
                "recommendation": recommendation,
                "recommendation_reason": (
                    "Insufficient distinct events/origins to decide." if not enough
                    else "Quantitative/calibration/operating/robustness gate fails."
                    if not quantitative else
                    "Retrospective quantitative checks pass, but pre-origin Yahoo vintages "
                    "do not exist; live point-in-time evidence is insufficient."
                ),
            }
    return report, leads


def markdown_report(report: dict) -> str:
    lines = [
        "# Transition Hazard Gate — RESEARCH / SHADOW", "",
        "**NOT VALIDATED / NOT FOR PORTFOLIO ACTION.** No change to frozen v1 or PM action.",
        "", report["data_policy"], "",
        "## Fixed protocol", json.dumps(report["protocol"], indent=2), "",
        "The 35/65 classifier cutoffs remain unchanged. Historical vintage availability "
        "fails every horizon's production evidence gate. Unconditional and duration-aware "
        "hazards are the baselines, not one-hot persistence. The market increment over "
        "duration is the primary comparison. Correlation between market features and "
        "the classifier-derived destination can create pseudo-predictability; this is "
        "a classifier-transition study, NOT an SPX-return forecast.",
        "", "## OOS transition hazards", "",
    ]
    for target in TARGETS:
        lines += [f"### {target}", ""]
        for h in HORIZONS:
            item = report["targets"][target][str(h)]
            lines += [
                f"#### {h} sessions — {item['recommendation']}",
                item["recommendation_reason"],
                f"Common OOS origins {item['origins']:,} ({item['first_oos_origin']}–"
                f"{item['last_oos_origin']}); {item['folds']} blocks; "
                f"event labels {item['event_labels']:,}, non-events {item['non_events']:,}; "
                f"distinct event dates {item['distinct_event_dates']:,}; base rate "
                f"{item['base_event_rate']:.2%}. Origin states: {item['origin_state_counts']}.",
                item["effective_sample_note"],
                "| Model | Log loss ↓ | Brier ↓ | AP ↑ | ROC-AUC (secondary) | ECE | Max bin gap | Calibration |",
                "|---|---:|---:|---:|---:|---:|---:|---|",
            ]
            for model in MODELS:
                metric = item["metrics"][model]
                cal = metric["calibration"]
                lines.append(
                    f"| {model} | {metric['log_loss']:.4f} | {metric['brier']:.4f} | "
                    f"{metric['average_precision']:.4f} | {metric['roc_auc_secondary']:.4f} | "
                    f"{cal['ece']:.4f} | {cal['max_bin_gap']:.4f} | "
                    f"{'PASS' if cal['pass'] else 'FAIL'} |"
                )
            for baseline, comparison in item["market_vs"].items():
                lines.append(
                    f"- Market vs {baseline}: relative LL gain "
                    f"{comparison['relative_log_loss_gain']:+.2%}, Brier gain "
                    f"{comparison['relative_brier_gain']:+.2%}; "
                    f"{comparison['dual_metric_fold_wins']}/{comparison['folds']} dual-metric "
                    "fold wins. Era deltas LL/Brier: "
                    + "; ".join(
                        f"{e['era']} {e['log_loss_delta']:+.4f}/{e['brier_delta']:+.4f}"
                        for e in comparison["chronological_thirds"]
                    )
                )
            lines += [
                "Fixed train-only top-decile operating point: "
                + json.dumps(item["market_operating_point"], sort_keys=True),
                "Classwise fixed-bin reliability: "
                + json.dumps({m: item["metrics"][m]["calibration"]["bins"] for m in MODELS}),
            ]
            if target == "de_risk_entry":
                lines.append("Entry lead diagnostic (all individual events in CSV): "
                             + json.dumps(item["lead_behavior"], sort_keys=True))
            lines += [
                f"Sample gate {item['sample_gate_pass']}; operating gate "
                f"{item['operating_gate_pass']}; sensitivity gate "
                f"{item['sensitivity_gate_pass']}; quantitative gate "
                f"{item['quantitative_gate_pass']}.", "",
            ]
    lines += [
        "## Fixed-cutoff sensitivity appendix (DE-RISK entry ONLY)",
        "Neither alternative changes the frozen classifier or selects a model. "
        "Changed event counts/gain direction signal label fragility.",
        "```json", json.dumps(report["sensitivity_appendix"], indent=2, sort_keys=True), "```",
        "", "## Decision",
        "No production promotion and no Signal Hub connection. The snapshot was retrieved "
        "after historical forecast origins; date-ordered retrospective evidence cannot "
        "certify live forecast availability.", "",
    ]
    return "\n".join(lines)