"""FREE SPX Daily Regime: observed Yahoo data only, with legacy research isolated."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from src.daily_signal import DEFAULT_START, refresh_free_signal
from src.free_signal_view import (
    INPUT_NAMES,
    NO_TAIL,
    decision_for_display,
    has_real_tail_inputs,
    load_verified_real_signal,
    observed_drivers,
    pm_action,
    retrieved_timestamp,
    score_label,
    session_date,
    tail_hedge_status,
)


st.set_page_config(
    page_title="SPX Daily Regime",
    page_icon="📈",
    layout="centered",
    initial_sidebar_state="collapsed",
)

FREE_SIGNAL_DIR = Path(__file__).resolve().parent / "data" / "free_signal"

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
        st.markdown("## HOLD / NO ACTION")
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
        st.write(f"**Tail Hedge:** {hedge}")
        st.write(
            f"**Confidence:** {latest.get('confidence') or 'Unavailable'}"
            f" · **Data quality:** {quality}"
        )
        st.caption(
            f"As-of session: {session_date(latest['date'])}"
            f" · Retrieved: {retrieved_timestamp(latest['retrieved_at_utc'])}"
        )
        if reason:
            st.warning(reason)
        if bundle.missing_inputs:
            st.caption("Missing real inputs: " + ", ".join(INPUT_NAMES[name] for name in bundle.missing_inputs))
        drivers = observed_drivers(latest.get("primary_drivers"), row)
        if drivers:
            st.markdown("**Observed-data drivers**\n\n" + "\n".join(f"- {driver}" for driver in drivers))
        else:
            st.caption("No attributable drivers available from observed inputs.")

with st.expander("View Analysis"):
    if bundle is not None:
        st.markdown("**RESEARCH SIGNAL / NOT CALIBRATED PROBABILITY**")
        st.caption("Observed Yahoo daily closes only; no missing close is filled.")
        st.markdown("#### Real market inputs at the as-of session")
        for field, ticker in INPUT_NAMES.items():
            value = row[field]
            st.write(
                f"**{ticker}** · {field.replace('_', ' ')}: "
                + (f"{float(value):,.2f}" if pd.notna(value) else "NOT AVAILABLE")
                + f" · Latest Yahoo observation: {bundle.latest_observation_dates.get(field) or 'NOT AVAILABLE'}"
            )
        st.write(
            "**Missing inputs:** "
            + (", ".join(INPUT_NAMES[name] for name in bundle.missing_inputs)
               if bundle.missing_inputs else "None")
        )
        st.caption(
            "Available closes are observed Yahoo inputs. Individual rolling components "
            "may need prior observations; no missing closes are filled."
        )
        st.markdown("#### Signal details")
        st.write(f"**Model regime:** {latest.get('regime') or 'Unavailable'}")
        if not eligible:
            st.caption(
                "The model's stored research result is not presented as today's PM action "
                "because current-data eligibility is not met."
            )
        st.write(f"**Overall stress score:** {score_label(latest.get('overall_stress_score'))}")
        st.write(f"**Body / repricing stress score:** {score_label(latest.get('body_stress_score'))}")
        st.markdown("#### Components contributing to this score")
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
            "See the free_daily_regime_v1 methodology for input transforms and windows."
        )
        if has_real_tail_inputs(row) and pd.notna(latest.get("tail_risk_hazard_score")):
            st.write(f"**Tail stress / hazard score:** {score_label(latest['tail_risk_hazard_score'])}")
            st.caption(
                "Tail Hedge display bands use this existing score: OFF ≤35, WATCH 35–65, "
                "ACTIVE ≥65. This is not a separate hedge model or trade instruction."
            )
        else:
            st.write("**Tail stress / hazard:** NOT AVAILABLE / INSUFFICIENT REAL DATA")
        if "recovery_score" in latest and pd.notna(latest["recovery_score"]):
            st.write(f"**Recovery score:** {score_label(latest['recovery_score'])}")
        st.write(f"**Confidence score:** {score_label(latest.get('confidence_score'))}")
        st.write(f"**Data lane:** {latest.get('data_lane') or 'Unavailable'}")
        st.write(f"**Available score components:** {latest.get('available_component_count', 'Unavailable')}/9")
        st.write(f"**Model version:** {latest.get('model_version') or 'Unavailable'}")
        st.write(f"**Probability status:** {latest.get('probability_status') or 'NOT_CALIBRATED'}")

        st.markdown("#### Recent real signal history")
        shown = 0
        for _, history_row in bundle.history.tail(5).iloc[::-1].iterrows():
            date = session_date(history_row["date"])
            inputs = bundle.canonical.loc[bundle.canonical["date"] == date]
            if len(inputs) != 1:
                continue
            observed = inputs.iloc[0]
            history_action = (
                pm_action(history_row["risk_signal"]) if pd.notna(observed.get("spx_close"))
                else "SIGNAL UNAVAILABLE — DATA FAILURE / INSUFFICIENT REAL DATA"
            )
            history_hedge = (
                tail_hedge_status(history_row.get("tail_risk_hazard_score"))
                if has_real_tail_inputs(observed) else NO_TAIL
            )
            with st.container(border=True):
                st.markdown(f"**{date} · {history_action}**")
                st.caption(
                    f"Historical tail research status ({date}): {history_hedge} · "
                    f"Confidence: {history_row.get('confidence') or 'Unavailable'}"
                )
            shown += 1
        if not shown:
            st.caption("No traceable historical signals available.")

    if st.button("Refresh real Yahoo daily data", width="stretch"):
        try:
            end = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
            with st.spinner("Downloading and scoring observed daily data…"):
                refresh_free_signal(DEFAULT_START, end, FREE_SIGNAL_DIR)
            st.rerun()
        except Exception as error:
            st.error(f"Yahoo refresh failed; no substitute data was used: {error}")