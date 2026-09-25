"""
app.py
======
SPX Flow Machine — Streamlit dashboard entry point.

Run with:
    streamlit run app.py

Pipeline:
  1. Generate synthetic intraday SPX price + options trades
  2. Enrich / classify trades
  3. Aggregate to 1-minute bars
  4. Build z-scored features
  5. Label 5m / 15m forward returns
  6. Compute flow score + direction
  7. Evaluate signal quality and run strategy
  8. Render dashboard
"""

import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd
import numpy as np

from src.generate_dummy_data import generate_spx_price, generate_options_trades
from src.classify_trades import enrich_trades
from src.make_bars import aggregate_to_bars
from src.build_features import build_features
from src.label_returns import label_returns
from src.score_flow import compute_flow_score
from src.evaluate_signal import full_evaluation
from src.daily_signal import DEFAULT_START, load_persisted_signal, refresh_free_signal
from src.free_signal_view import (
    pm_action, tail_hedge_status, short_drivers, session_date,
    retrieved_timestamp, score_label,
)
from src import plots


# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="SPX Daily Regime | SPX Flow Machine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ── Sidebar controls ─────────────────────────────────────────────────────────

FREE_SIGNAL_DIR = Path(__file__).resolve().parent / "data" / "free_signal"

with st.sidebar:
    st.title("⚡ Controls")
    st.markdown("---")
    st.subheader("FREE Daily Signal")
    refresh_free = st.button(
        "Refresh Yahoo signal",
        use_container_width=True,
        help="Download available free daily series and persist a causal signal.",
    )
    st.caption("Real daily Yahoo data. No options-chain input.")
    st.markdown("---")

    seed = st.number_input(
        "Random seed",
        min_value=0,
        max_value=9999,
        value=42,
        step=1,
        help="Change to regenerate synthetic data with a different random path.",
    )

    if st.button("🎲 Regenerate", use_container_width=True):
        seed = np.random.randint(0, 9999)
        st.rerun()

    st.markdown("---")

    horizon = st.selectbox(
        "Forward return horizon",
        options=["5m", "15m"],
        index=0,
        help="Horizon for labels, hit rate, and strategy PnL.",
    )

    threshold = st.slider(
        "Signal threshold (±)",
        min_value=1.0,
        max_value=8.0,
        value=3.0,
        step=0.5,
        help="Flow score magnitude required to enter a long or short position.",
        key="signal_threshold",
    )

    cost_bps = st.slider(
        "Transaction cost (bps)",
        min_value=0.0,
        max_value=5.0,
        value=1.0,
        step=0.25,
        help="One-way cost per trade in basis points.",
    )

    st.markdown("---")
    st.caption("**Intraday data mode:** Synthetic (dummy)")
    st.caption("**Replace with:** Databento OPRA ticks")
    st.caption("See README.md for integration notes.")


# ── Data pipeline ─────────────────────────────────────────────────────────────

free_refresh_error = None
if refresh_free:
    try:
        exclusive_end = (
            datetime.now(timezone.utc).date() + timedelta(days=1)
        ).isoformat()
        with st.spinner("Refreshing real Yahoo daily signal…"):
            refresh_free_signal(DEFAULT_START, exclusive_end, FREE_SIGNAL_DIR)
    except Exception as error:
        free_refresh_error = str(error)


# ── FREE real-data daily signal ───────────────────────────────────────────────

st.title("SPX Daily Regime")
if free_refresh_error:
    st.error(f"Yahoo refresh failed: {free_refresh_error}")

free_latest, free_history = load_persisted_signal(FREE_SIGNAL_DIR)
if free_latest is None:
    st.warning("No daily signal is available. No portfolio action is indicated.")
    st.caption("The optional Yahoo refresh is in Controls; no synthetic intraday data is used here.")
else:
    with st.container(border=True):
        st.caption("FREE · DAILY SIGNAL · YAHOO HISTORICAL RESEARCH")
        st.markdown(f"## {pm_action(free_latest.get('risk_signal'))}")
        st.write(f"**Tail Hedge:** {tail_hedge_status(free_latest.get('tail_risk_hazard_score'))}")
        st.write(
            f"**Confidence:** {free_latest.get('confidence') or 'Unavailable'}"
            f"  ·  **Data quality:** {free_latest.get('data_quality') or 'Unavailable'}"
        )
        st.caption(
            f"As-of session: {session_date(free_latest.get('date'))}"
            f" · Source retrieved: {retrieved_timestamp(free_latest.get('retrieved_at_utc'))}"
        )
        drivers = short_drivers(free_latest.get("primary_drivers"))
        if drivers:
            st.markdown("**Main drivers**\n\n" + "\n".join(f"- {driver}" for driver in drivers))
        else:
            st.caption("No drivers available.")

    with st.expander("View Analysis"):
        st.caption(
            "These are empirical stress scores, not calibrated probabilities. "
            "Tail Hedge is a display status based on the existing tail score: "
            "OFF ≤35, WATCH >35 and <65, ACTIVE ≥65. It is not a separate hedge model or execution instruction."
        )
        st.write(f"**Regime:** {free_latest.get('regime') or 'Unavailable'}")
        st.write(f"**Overall stress score:** {score_label(free_latest.get('overall_stress_score'))}")
        st.write(f"**Body / repricing stress score:** {score_label(free_latest.get('body_stress_score'))}")
        st.write(f"**Tail stress / hazard score:** {score_label(free_latest.get('tail_risk_hazard_score'))}")
        if "recovery_score" in free_latest and pd.notna(free_latest["recovery_score"]):
            st.write(f"**Recovery score:** {score_label(free_latest['recovery_score'])}")
        st.markdown("**Model & data quality**")
        st.write(f"Model: {free_latest.get('model_version') or 'Unavailable'}")
        st.write(f"Data lane: {free_latest.get('data_lane') or 'Unavailable'}")
        st.write(
            f"Confidence score: {score_label(free_latest.get('confidence_score'))}"
            f" · Available components: {free_latest.get('available_component_count', 'Unavailable')}/9"
        )
        st.write(f"Score type: {free_latest.get('score_type') or 'Empirical score'}")
        st.write(f"Probability status: {free_latest.get('probability_status') or 'NOT_CALIBRATED'}")
        st.write(f"Missing inputs: {free_latest.get('missing_inputs') or 'None reported'}")
        st.caption("Yahoo historical data is research-only; not a recorded live portfolio instruction.")

        st.markdown("#### Recent signal history")
        if free_history.empty:
            st.caption("No recent history available.")
        else:
            for _, row in free_history.tail(5).iloc[::-1].iterrows():
                with st.container(border=True):
                    st.markdown(f"**{session_date(row['date'])} · {pm_action(row.get('risk_signal'))}**")
                    st.caption(
                        f"Tail Hedge: {tail_hedge_status(row.get('tail_risk_hazard_score'))}"
                        f" · Confidence: {row.get('confidence') or 'Unavailable'}"
                    )


# ── Legacy synthetic intraday research (unchanged) ───────────────────────────

st.markdown("---")
st.caption("The intraday options-flow research below remains fully synthetic.")
st.markdown(
    "<h2 style='margin-bottom:0'>⚡ SPX Flow Machine</h2>"
    "<p style='color:#8B8FA8;font-size:15px;margin-top:4px'>"
    "Options flow → directional pressure → 5m/15m forward returns</p>",
    unsafe_allow_html=True,
)

@st.cache_data(show_spinner=False)
def run_pipeline(seed: int):
    spx_df = generate_spx_price(seed=seed)
    trades_raw = generate_options_trades(spx_df, seed=seed)
    trades = enrich_trades(trades_raw)
    bars = aggregate_to_bars(trades, spx_df)
    bars = build_features(bars)
    bars = label_returns(bars)
    bars = compute_flow_score(bars)
    return spx_df, trades, bars


with st.spinner("Running pipeline…"):
    spx_df, trades, bars = run_pipeline(seed)

eval_results = full_evaluation(
    bars,
    threshold=threshold,
    cost_bps=cost_bps,
    horizon=horizon,
)

latest = bars.dropna(subset=["flow_score"]).iloc[-1] if len(bars) > 0 else None


# ── KPI cards ─────────────────────────────────────────────────────────────────

direction_color = {
    "Bullish": "#00C896",
    "Bearish": "#FF4B6E",
    "Neutral": "#8B8FA8",
}
confidence_color = {"High": "#00C896", "Medium": "#F0A500", "Low": "#8B8FA8"}

flow_score_val = float(latest["flow_score"]) if latest is not None else 0.0
flow_dir = str(latest["flow_direction"]) if latest is not None else "Neutral"
flow_conf = str(latest["flow_confidence"]) if latest is not None else "Low"
latest_price = float(latest["spx_price"]) if latest is not None else 0.0

hit_rates = eval_results["hit_rates"]
bull_hit = f"{hit_rates['bullish_hit_rate']:.1f}%" if not pd.isna(hit_rates.get("bullish_hit_rate", float("nan"))) else "—"
total_pnl = eval_results["total_pnl_bps"]

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    color = "#00C896" if flow_score_val > 2 else "#FF4B6E" if flow_score_val < -2 else "#8B8FA8"
    st.metric("Flow Score", f"{flow_score_val:+.1f}", help="Current normalized flow score (-10 to +10).")

with col2:
    dc = direction_color.get(flow_dir, "#8B8FA8")
    st.markdown(
        f"<div style='font-size:12px;color:#8B8FA8;margin-bottom:4px'>Direction</div>"
        f"<div style='font-size:24px;font-weight:700;color:{dc}'>{flow_dir}</div>",
        unsafe_allow_html=True,
    )

with col3:
    cc = confidence_color.get(flow_conf, "#8B8FA8")
    st.markdown(
        f"<div style='font-size:12px;color:#8B8FA8;margin-bottom:4px'>Confidence</div>"
        f"<div style='font-size:24px;font-weight:700;color:{cc}'>{flow_conf}</div>",
        unsafe_allow_html=True,
    )

with col4:
    st.metric("SPX Price", f"${latest_price:,.2f}", help="Latest synthetic SPX mid price.")

with col5:
    st.metric(
        f"{horizon.upper()} Hit Rate (Bull)",
        bull_hit,
        help=f"Directional accuracy when flow_direction = Bullish, {horizon} horizon.",
    )

with col6:
    pnl_color = "normal" if total_pnl >= 0 else "inverse"
    st.metric(
        "Strategy PnL",
        f"{total_pnl:+.1f} bps",
        help=f"Cumulative long/short PnL at ±{threshold:.1f} threshold, {cost_bps:.2f} bps cost.",
    )

st.markdown("---")


# ── Charts — row 1 ────────────────────────────────────────────────────────────

c1, c2 = st.columns(2)

with c1:
    st.plotly_chart(plots.plot_spx_price(bars), use_container_width=True)
    st.caption("Synthetic SPX intraday price path. Generated via geometric Brownian motion with injected regime shocks.")

with c2:
    st.plotly_chart(plots.plot_flow_score(bars), use_container_width=True)
    st.caption(
        "Rolling z-scored options flow score. "
        "Green bars > +2 (Bullish), red bars < −2 (Bearish), gray = Neutral. "
        "Dashed lines mark ±2 thresholds."
    )


# ── Charts — row 2 ────────────────────────────────────────────────────────────

c3, c4 = st.columns(2)

with c3:
    st.plotly_chart(plots.plot_score_vs_return(bars, horizon), use_container_width=True)
    st.caption(
        f"Each point is one 1-minute bar. Dashed line = linear fit. "
        f"A positive slope indicates the flow score has predictive value for {horizon} returns."
    )

with c4:
    bucket_df = eval_results["bucket_table"]
    st.plotly_chart(plots.plot_return_by_bucket(bucket_df, horizon), use_container_width=True)
    st.caption(
        f"Average {horizon} log-return (bps) bucketed by flow score. "
        f"Monotonically increasing bars support the signal hypothesis."
    )


# ── Charts — row 3 ────────────────────────────────────────────────────────────

c5, c6 = st.columns(2)

with c5:
    st.plotly_chart(plots.plot_cumulative_pnl(eval_results["strategy_df"]), use_container_width=True)
    st.caption(
        f"Long when score > +{threshold:.1f}, short when < −{threshold:.1f}, flat otherwise. "
        f"Cost: {cost_bps:.2f} bps/trade. PnL in basis points."
    )

with c6:
    st.plotly_chart(plots.plot_notional_breakdown(bars), use_container_width=True)
    st.caption(
        "Call buying / put selling (above zero = bullish pressure), "
        "put buying / call selling (below zero = bearish pressure), in $M notional."
    )


# ── Tables ────────────────────────────────────────────────────────────────────

st.markdown("---")
st.subheader("Latest 20 Flow Bars")

display_cols = [
    "minute", "spx_price", "flow_score", "flow_direction", "flow_confidence",
    "total_notional", "sweep_count", "net_delta_notional",
    f"ret_{horizon}", f"direction_{horizon}",
]
display_cols = [c for c in display_cols if c in bars.columns]

latest_bars = bars[display_cols].tail(20).copy()
latest_bars["minute"] = latest_bars["minute"].dt.strftime("%H:%M")
latest_bars["spx_price"] = latest_bars["spx_price"].map("${:,.2f}".format)
latest_bars["total_notional"] = (latest_bars["total_notional"] / 1e6).map("{:.2f}M".format)
latest_bars["net_delta_notional"] = (latest_bars["net_delta_notional"] / 1e6).map("{:.2f}M".format)
if f"ret_{horizon}" in latest_bars.columns:
    latest_bars[f"ret_{horizon}"] = (latest_bars[f"ret_{horizon}"] * 10000).map("{:.1f} bps".format)

latest_bars.columns = [c.replace("_", " ").title() for c in latest_bars.columns]
st.dataframe(latest_bars, use_container_width=True, hide_index=True)


# ── Evaluation summary ────────────────────────────────────────────────────────

st.subheader("Evaluation Summary")

sharpe = eval_results["sharpe"]
max_dd = eval_results["max_drawdown_bps"]
n_trades = eval_results["n_trades"]

summary_data = {
    "Metric": [
        "Bullish signal hit rate",
        "Bearish signal hit rate",
        "Bullish signal count",
        "Bearish signal count",
        "Strategy total PnL (bps)",
        "Daily Sharpe (approx)",
        "Max drawdown (bps)",
        "Number of trades",
        "Threshold used",
        "Cost per trade (bps)",
        "Horizon",
    ],
    "Value": [
        f"{hit_rates.get('bullish_hit_rate', float('nan')):.1f}%" if not pd.isna(hit_rates.get("bullish_hit_rate", float("nan"))) else "—",
        f"{hit_rates.get('bearish_hit_rate', float('nan')):.1f}%" if not pd.isna(hit_rates.get("bearish_hit_rate", float("nan"))) else "—",
        str(hit_rates.get("bullish_n", 0)),
        str(hit_rates.get("bearish_n", 0)),
        f"{total_pnl:+.1f}",
        f"{sharpe:.2f}" if not (sharpe is None or (isinstance(sharpe, float) and np.isnan(sharpe))) else "—",
        f"{max_dd:.1f}",
        str(n_trades),
        f"±{threshold:.1f}",
        f"{cost_bps:.2f}",
        horizon.upper(),
    ],
}

summary_df = pd.DataFrame(summary_data)
st.dataframe(summary_df, use_container_width=True, hide_index=True)

st.markdown("---")
st.caption(
    "⚠️  **The intraday options-flow section is synthetic.** "
    "The FREE daily panel above uses real Yahoo Finance data. "
    "Signal strength is artificially injected (SNR ≈ 0.3). "
    "Results do not reflect real tradeable alpha. "
    "See README.md for how to connect real Databento OPRA data."
)
