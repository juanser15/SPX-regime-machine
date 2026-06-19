"""
plots.py
========
Plotly chart builders for the SPX Flow Machine dashboard.

All functions return plotly.graph_objects.Figure objects.
Color palette is designed for dark-mode institutional use.
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np


BULLISH_COLOR = "#00C896"
BEARISH_COLOR = "#FF4B6E"
NEUTRAL_COLOR = "#8B8FA8"
ACCENT_COLOR = "#4F8EF7"
BG_COLOR = "#0E1117"
GRID_COLOR = "#1E2130"
TEXT_COLOR = "#C8CDD8"

LAYOUT_DEFAULTS = dict(
    paper_bgcolor=BG_COLOR,
    plot_bgcolor=BG_COLOR,
    font=dict(color=TEXT_COLOR, family="Inter, sans-serif", size=12),
    margin=dict(l=50, r=20, t=40, b=40),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="rgba(0,0,0,0)"),
    xaxis=dict(gridcolor=GRID_COLOR, showgrid=True, zeroline=False),
    yaxis=dict(gridcolor=GRID_COLOR, showgrid=True, zeroline=False),
)


def _apply_layout(fig: go.Figure, **overrides) -> go.Figure:
    layout = {**LAYOUT_DEFAULTS, **overrides}
    fig.update_layout(**layout)
    return fig


def plot_spx_price(bars: pd.DataFrame) -> go.Figure:
    """SPX price line chart over the trading day."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=bars["minute"],
        y=bars["spx_price"],
        mode="lines",
        line=dict(color=ACCENT_COLOR, width=1.8),
        name="SPX Price",
        hovertemplate="%{x|%H:%M}  $%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text="SPX Price", font=dict(size=14)),
        yaxis_title="Price ($)",
    )
    return _apply_layout(fig)


def plot_flow_score(bars: pd.DataFrame) -> go.Figure:
    """Flow score time series with color-coded direction bands."""
    fig = go.Figure()

    colors = bars["flow_direction"].map(
        {"Bullish": BULLISH_COLOR, "Bearish": BEARISH_COLOR, "Neutral": NEUTRAL_COLOR}
    ).fillna(NEUTRAL_COLOR)

    fig.add_trace(go.Bar(
        x=bars["minute"],
        y=bars["flow_score"],
        marker_color=colors,
        name="Flow Score",
        hovertemplate="%{x|%H:%M}  Score: %{y:.2f}<extra></extra>",
    ))

    fig.add_hline(y=2, line_dash="dot", line_color=BULLISH_COLOR, opacity=0.5)
    fig.add_hline(y=-2, line_dash="dot", line_color=BEARISH_COLOR, opacity=0.5)
    fig.add_hline(y=0, line_color=NEUTRAL_COLOR, opacity=0.3)

    fig.update_layout(
        title=dict(text="Flow Score Over Time", font=dict(size=14)),
        yaxis_title="Flow Score",
        yaxis=dict(range=[-11, 11], gridcolor=GRID_COLOR, zeroline=False),
    )
    return _apply_layout(fig)


def plot_score_vs_return(bars: pd.DataFrame, horizon: str = "5m") -> go.Figure:
    """Scatter plot: flow score vs forward return."""
    ret_col = f"ret_{horizon}"
    valid = bars.dropna(subset=[ret_col, "flow_score"])

    colors = valid["flow_direction"].map(
        {"Bullish": BULLISH_COLOR, "Bearish": BEARISH_COLOR, "Neutral": NEUTRAL_COLOR}
    ).fillna(NEUTRAL_COLOR)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=valid["flow_score"],
        y=valid[ret_col] * 10_000,
        mode="markers",
        marker=dict(color=colors, size=5, opacity=0.7),
        text=valid["minute"].dt.strftime("%H:%M"),
        hovertemplate="Score: %{x:.1f}<br>Return: %{y:.1f} bps<br>Time: %{text}<extra></extra>",
        name="",
    ))

    # Add linear trend line
    if len(valid) > 2:
        z = np.polyfit(valid["flow_score"], valid[ret_col] * 10_000, 1)
        p = np.poly1d(z)
        x_line = np.linspace(valid["flow_score"].min(), valid["flow_score"].max(), 100)
        fig.add_trace(go.Scatter(
            x=x_line, y=p(x_line),
            mode="lines",
            line=dict(color="white", width=1.2, dash="dash"),
            name="Trend",
            hoverinfo="skip",
        ))

    fig.update_layout(
        title=dict(text=f"Flow Score vs {horizon.upper()} Forward Return", font=dict(size=14)),
        xaxis_title="Flow Score",
        yaxis_title=f"{horizon.upper()} Return (bps)",
    )
    return _apply_layout(fig)


def plot_return_by_bucket(bucket_df: pd.DataFrame, horizon: str = "5m") -> go.Figure:
    """Bar chart: average forward return by score bucket."""
    colors = [
        BEARISH_COLOR if v < 0 else BULLISH_COLOR
        for v in bucket_df["avg_return_bps"]
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=bucket_df["bucket"].astype(str),
        y=bucket_df["avg_return_bps"],
        marker_color=colors,
        text=bucket_df["count"].apply(lambda x: f"n={x}"),
        textposition="outside",
        textfont=dict(size=10),
        hovertemplate="Bucket: %{x}<br>Avg Return: %{y:.1f} bps<br>%{text}<extra></extra>",
        name="",
    ))
    fig.add_hline(y=0, line_color=NEUTRAL_COLOR, opacity=0.5)
    fig.update_layout(
        title=dict(text=f"Avg {horizon.upper()} Return by Score Bucket", font=dict(size=14)),
        xaxis_title="Score Bucket",
        yaxis_title="Avg Return (bps)",
    )
    return _apply_layout(fig)


def plot_cumulative_pnl(strategy_df: pd.DataFrame) -> go.Figure:
    """Cumulative strategy PnL in basis points."""
    fig = go.Figure()

    pnl_bps = strategy_df["cum_pnl"] * 10_000

    fig.add_trace(go.Scatter(
        x=strategy_df["minute"],
        y=pnl_bps,
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(79,142,247,0.12)",
        line=dict(color=ACCENT_COLOR, width=2),
        name="Cumulative PnL",
        hovertemplate="%{x|%H:%M}  PnL: %{y:.1f} bps<extra></extra>",
    ))

    fig.add_hline(y=0, line_color=NEUTRAL_COLOR, opacity=0.4)
    fig.update_layout(
        title=dict(text="Strategy Cumulative PnL", font=dict(size=14)),
        yaxis_title="Cumulative Return (bps)",
    )
    return _apply_layout(fig)


def plot_notional_breakdown(bars: pd.DataFrame) -> go.Figure:
    """Stacked area chart: notional breakdown by call/put buy/sell."""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=bars["minute"], y=bars["call_buy_notional"] / 1e6,
        mode="lines", stackgroup="bull",
        line=dict(width=0), fillcolor="rgba(0,200,150,0.5)",
        name="Call Buy", hovertemplate="%{y:.1f}M<extra>Call Buy</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=bars["minute"], y=bars["put_sell_notional"] / 1e6,
        mode="lines", stackgroup="bull",
        line=dict(width=0), fillcolor="rgba(0,200,150,0.25)",
        name="Put Sell", hovertemplate="%{y:.1f}M<extra>Put Sell</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=bars["minute"], y=-(bars["put_buy_notional"] / 1e6),
        mode="lines", stackgroup="bear",
        line=dict(width=0), fillcolor="rgba(255,75,110,0.5)",
        name="Put Buy", hovertemplate="%{y:.1f}M<extra>Put Buy</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=bars["minute"], y=-(bars["call_sell_notional"] / 1e6),
        mode="lines", stackgroup="bear",
        line=dict(width=0), fillcolor="rgba(255,75,110,0.25)",
        name="Call Sell", hovertemplate="%{y:.1f}M<extra>Call Sell</extra>",
    ))

    fig.add_hline(y=0, line_color=NEUTRAL_COLOR, opacity=0.4)
    fig.update_layout(
        title=dict(text="Notional Flow Breakdown ($M)", font=dict(size=14)),
        yaxis_title="Notional ($M)",
    )
    return _apply_layout(fig)
