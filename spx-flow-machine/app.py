"""FREE SPX Daily Regime: observed Yahoo data only, with legacy research isolated."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from src.daily_signal import DEFAULT_START, refresh_free_signal
from src.analysis_view import (
    factor_cards, forward_returns, observed_history, plain_drivers,
    recent_cards, regime_figure, return_summary, returns_figure,
)
from src.free_signal_view import (
    INPUT_NAMES,
    NO_TAIL,
    decision_for_display,
    has_real_tail_inputs,
    load_verified_real_signal,
    retrieved_timestamp,
    score_label,
    session_date,
    tail_hedge_status,
)
from src.regime_outlook_view import load_shadow_report


st.set_page_config(
    page_title="SPX Daily Regime",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

FREE_SIGNAL_DIR = Path(__file__).resolve().parent / "data" / "free_signal"
st.markdown(
    """<style>
    @media (max-width: 640px) {
      .block-container { padding: 1rem 0.85rem 3rem; max-width: 100%; }
      [data-testid="stPlotlyChart"], [data-testid="stPlotlyChart"] > div {
        max-width: 100%; min-width: 0;
      }
    }
    </style>""",
    unsafe_allow_html=True,
)

st.title("SPX Daily Regime")
try:
    bundle = load_verified_real_signal(FREE_SIGNAL_DIR)
    load_error = None
except (OSError, ValueError, KeyError, pd.errors.ParserError) as error:
    bundle = None
    load_error = str(error)

if bundle is None:
    with st.container(border=True):
        st.caption("DATA = REAL · YAHOO FINANCE DAILY · NO VERIFIED SNAPSHOT")
        st.markdown("## SIGNAL UNAVAILABLE")
        st.write(f"**Tail Hedge:** {NO_TAIL}")
        st.write("**Confidence:** Unavailable · **Data quality:** Unavailable")
        st.caption("As-of: unavailable. No real signal can be verified.")
    st.error(f"Real-data signal unavailable: {load_error}")
else:
    latest = bundle.latest
    row = bundle.input_row
    action, eligible, reason = decision_for_display(
        latest, row, current_failure=bundle.current_failure,
    )
    hedge = (
        tail_hedge_status(latest.get("tail_risk_hazard_score"))
        if eligible and has_real_tail_inputs(row) else NO_TAIL
    )
    quality = "COMPLETE" if not bundle.missing_inputs else "DEGRADED_MISSING_INPUTS"
    with st.container(border=True):
        st.caption(f"DATA = REAL · {bundle.source.upper()} DAILY · RESEARCH ONLY")
        st.markdown(f"## {action}")
        st.write(f"**Tail Hedge:** {hedge} · **Confidence:** {latest.get('confidence') or 'Unavailable'}")
        st.caption(f"As-of: {session_date(latest['date'])} · Data quality: {quality}")
        if reason:
            st.warning(reason)
        drivers = plain_drivers(latest.get("primary_drivers"), row)
        if drivers:
            st.markdown("**Why this reading**\n\n" + "\n".join(f"- {driver}" for driver in drivers))
        else:
            st.caption("No attributable drivers available from observed inputs.")

if st.toggle("View Analysis"):
    if bundle is None:
        st.info("No verified real Yahoo signal snapshot is available for analysis.")
    else:
        st.markdown("### 1 · Regime history")
        window = st.selectbox("Time window", ("1M", "3M", "1Y", "MAX"), index=2)
        chart_data = observed_history(bundle.history, bundle.canonical)
        if chart_data.empty:
            st.info("No published regime dates with an observed SPX close.")
        else:
            st.plotly_chart(regime_figure(chart_data, window), width="stretch",
                            config={"displayModeBar": False})
            displayed = chart_data if window == "MAX" else chart_data.loc[
                chart_data["date"] >= chart_data["date"].max()
                - pd.DateOffset(months={"1M": 1, "3M": 3, "1Y": 12}[window])
            ]
            st.caption(
                f"Observed SPX closes and persisted regime signals · "
                f"{session_date(displayed.iloc[0]['date'])} to {session_date(displayed.iloc[-1]['date'])}. "
                "Past signals are causal research reconstructions, not a record of live decisions. "
                "Shaded bands, when visible, are market event context only; they do not classify regimes."
            )
        st.markdown("**Recent history**")
        cards = recent_cards(bundle.history, bundle.canonical)
        if not cards:
            st.caption("No traceable historical signals available.")
        for item in cards:
            with st.container(border=True):
                st.markdown(f"**{item['date']} · {item['action']}**")
                st.caption(f"Confidence: {item['confidence']} · Historical tail: {item['tail']}")

        st.markdown("### 2 · Regime vs market returns")
        st.caption("DESCRIPTIVE VALIDATION — NOT A BACKTEST")
        returns = forward_returns(bundle.history, bundle.canonical)
        if returns.empty:
            st.info("Not enough completed, observed SPX sessions after the available signals for a five-session comparison.")
        else:
            st.plotly_chart(returns_figure(returns), width="stretch",
                            config={"displayModeBar": False})
            st.caption(
                "SPX close-to-close return over the next five observed trading sessions after "
                "each persisted regime date; missing closes and unpublished outcomes are excluded. "
                f"Paired dates: {session_date(returns.iloc[0]['date'])} to "
                f"{session_date(returns.iloc[-1]['date'])}. Overlapping windows are not independent. "
                "Historical regimes were reconstructed after the fact from real Yahoo closes."
            )
            for summary in return_summary(returns):
                with st.container(border=True):
                    st.markdown(f"**{('HOLD / NEUTRAL' if summary['state'] == 'NEUTRAL' else summary['state'])}**")
                    st.caption(
                        f"{summary['count']:,} observations · Median next-5-session SPX return: "
                        f"{summary['median']:+.2f}% · Downside frequency: {summary['downside']:.1f}%"
                        if summary["count"] else "No observations"
                    )

        st.markdown("### 3 · Why today?")
        st.caption(f"Latest published session: {session_date(latest['date'])} · "
                   "These are explanations of the stored score, not separate signals.")
        if not eligible:
            st.warning("No current eligible decision. Factors below describe the last published research session only.")
        for factor in factor_cards(bundle.components, row):
            with st.container(border=True):
                st.markdown(f"**{factor['title']} · {factor['status']}**")
                st.caption(f"Observed: {factor['observations']}")
                st.write(
                    f"Stress reading: {factor['score']:.0f}/100 · {factor['explanation']}"
                    if factor["score"] is not None else factor["explanation"]
                )

        with st.expander("Technical details / methodology"):
            st.caption("Verified Yahoo Finance daily inputs; no filled missing closes.")
            st.write(f"**Stored model regime:** {latest.get('regime') or 'Unavailable'}")
            st.write(f"**As-of session:** {session_date(latest['date'])} · "
                     f"**Retrieved:** {retrieved_timestamp(latest['retrieved_at_utc'])}")
            st.write(f"**Signal snapshot:** {bundle.signal_snapshot_id}")
            st.write(f"**Input snapshot:** {latest.get('data_snapshot_id') or 'Unavailable'}")
            audit_path = FREE_SIGNAL_DIR / "audits" / f"{bundle.signal_snapshot_id}.jsonl"
            if audit_path.exists():
                audit_record = json.loads(audit_path.read_text().splitlines()[-1])
                if (audit_record.get("signal_snapshot_id") == bundle.signal_snapshot_id
                        and audit_record.get("input_data_snapshot_id") == latest.get("data_snapshot_id")
                        and audit_record.get("date") == latest["date"]):
                    st.write(f"**Calculated at:** {retrieved_timestamp(audit_record.get('calculated_at_utc'))}")
                    st.write(f"**Historically available no earlier than:** "
                             f"{retrieved_timestamp(audit_record.get('available_at_utc'))}")
                else:
                    st.warning("Audit availability timestamps do not match the verified signal snapshot.")
            else:
                st.warning("Audit availability timestamps are unavailable for this snapshot.")
            st.write(f"**Model version:** {latest.get('model_version') or 'Unavailable'}")
            st.write(f"**Data lane:** {latest.get('data_lane') or 'Unavailable'} · "
                     f"**Data quality:** {quality}")
            st.write("**Missing tickers:** " + (
                ", ".join(INPUT_NAMES[name] for name in bundle.missing_inputs)
                if bundle.missing_inputs else "None"
            ))
            for field, ticker in INPUT_NAMES.items():
                value = row[field]
                st.write(
                    f"**{ticker}** ({field}): "
                    + (f"{float(value):,.2f}" if pd.notna(value) else "NOT AVAILABLE")
                    + f" · Latest Yahoo observation: {bundle.latest_observation_dates.get(field) or 'NOT AVAILABLE'}"
                )
            st.write(f"**Overall stress score:** {score_label(latest.get('overall_stress_score'))}")
            st.write(f"**Body stress score:** {score_label(latest.get('body_stress_score'))}")
            st.write(f"**Tail stress score:** {score_label(latest.get('tail_risk_hazard_score'))}")
            st.write(f"**Confidence score:** {score_label(latest.get('confidence_score'))}")
            st.write(f"**Available components:** {latest.get('available_component_count', 'Unavailable')}/9")
            st.write(f"**Stored primary drivers:** {latest.get('primary_drivers') or 'Unavailable'}")
            st.write(f"**Probability status:** {latest.get('probability_status') or 'NOT_CALIBRATED'}")
            for part in bundle.components:
                st.write(
                    f"**{part['name']}** ({part['group']}) · "
                    f"{part['transformation']} = {float(part['transformed_value']):.6g} · "
                    f"trailing percentile {float(part['percentile_score']):.4f}/100 · "
                    f"base weight {float(part['base_weight']):.0%} · "
                    f"effective weight {float(part['effective_weight']):.4%} · "
                    f"contribution {float(part['weighted_points']):.4f} points"
                )
            st.caption(
                "Only available components contribute. Weights renormalize within body and tail; "
                "overall = 75% body + 25% tail when tail exists, otherwise 100% body. "
                "Tail Hedge display bands use the existing tail score: OFF ≤35, WATCH 35–65, ACTIVE ≥65. "
                "Not a calibrated probability, hedge recommendation, or trading signal. "
                "Historical availability is no earlier than the actual Yahoo retrieval and calculation timestamps."
            )
            st.markdown((Path(__file__).parent / "docs" / "free_daily_regime_v1_methodology.md").read_text())
            if st.button("Refresh real Yahoo daily data", width="stretch"):
                try:
                    end = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
                    with st.spinner("Downloading and scoring observed daily data…"):
                        refresh_free_signal(DEFAULT_START, end, FREE_SIGNAL_DIR)
                    st.rerun()
                except Exception as error:
                    st.error(f"Yahoo refresh failed; no substitute data was used: {error}")

with st.expander("Regime Outlook — RESEARCH / SHADOW"):
    st.error("NOT VALIDATED / NOT FOR PORTFOLIO ACTION")
    st.caption(
        "Separate, retrospective research only. The current-state action above remains authoritative. "
        "These are not historical live forecasts or a prediction of the next regime."
    )
    if bundle is None:
        st.info("No verified current-state snapshot is available for a shadow research report.")
    else:
        try:
            outlook, report_text = load_shadow_report(
                Path(__file__).parent / "research" / "regime_outlook",
                bundle.signal_snapshot_id, latest["data_snapshot_id"], FREE_SIGNAL_DIR,
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            st.warning(f"No matching verified shadow report: {error}")
        else:
            horizon = st.selectbox("Research horizon (trading sessions)", ("1", "3", "5"),
                                   format_func=lambda value: f"{value}D")
            result = outlook["horizons"][horizon]
            st.markdown(f"**{horizon}D recommendation: {result['recommendation']}**")
            st.write(result["recommendation_reason"])
            st.caption(
                f"{result['n_common_oos_origins']:,} common date-ordered OOS origins "
                f"({result['first_oos_origin']}–{result['last_oos_origin']}); "
                f"{result['folds']} chronological test blocks. "
                f"{result['counts']['distinct_one_step_changes']} distinct adjacent state changes. "
                "Historical Yahoo vintages were not captured at each session."
            )
            for model in ("persistence", "unconditional", "markov", "logistic"):
                metric = result["metrics"][model]
                with st.container(border=True):
                    st.markdown(f"**{model.title()} · transition scores**")
                    st.caption(
                        f"Log loss {metric['log_loss']:.3f} · Multiclass Brier "
                        f"{metric['multiclass_brier']:.3f} · Calibration "
                        f"{'pass' if metric['calibration_pass'] else 'fail'} · "
                        f"Mean max score {metric['mean_max_score']:.2f}"
                    )
            st.caption(
                "Destination frequencies: " +
                " · ".join(
                    f"{state.replace('NEUTRAL', 'HOLD / NEUTRAL')} "
                    f"{count:,}"
                    for state, count in result["counts"]["destination_class_counts"].items()
                )
            )
            for model in ("markov", "logistic"):
                lead = result["lead_behavior"][model]
                medians = lead["median_de_risk_score_prior_sessions"]
                alarm = lead["false_alarms"][horizon]
                st.caption(
                    f"{model.title()} · DE-RISK entry lead sample: "
                    f"{lead['matched_distinct_de_risk_entries']} distinct entries · "
                    f"median scores at −5/−3/−1 sessions: "
                    + " / ".join(
                        f"{medians[f'minus_{n}']:.2f}" if medians[f"minus_{n}"] is not None else "n/a"
                        for n in (5, 3, 1)
                    )
                    + f" · Rising scores without a DE-RISK destination: "
                    f"{alarm['rising_score_without_de_risk_destination']}/"
                    f"{alarm['rising_score_origins']}"
                    + f" · {horizon}D false alarms above 0.50: "
                    f"{alarm['false_alarms']}/{alarm['alerts']}"
                )
            st.caption(
                "Full report includes classwise reliability bins, fold and era comparisons, "
                "transition frequencies, confusion matrices, coefficients, and provenance."
            )
            st.download_button(
                "Download research gate report",
                data=report_text, file_name="regime-outlook-research.md",
                mime="text/markdown", width="stretch",
            )