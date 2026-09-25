"""Presentation-only views of verified, persisted daily signals and Yahoo closes."""

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.free_signal_view import NO_TAIL, has_real_tail_inputs, pm_action, session_date, tail_hedge_status

STATES = ("RISK-ON", "NEUTRAL", "DE-RISK")
LABELS = {"RISK-ON": "RISK-ON", "NEUTRAL": "HOLD / NEUTRAL", "DE-RISK": "DE-RISK"}
COLORS = {"RISK-ON": "#38bfa1", "NEUTRAL": "#e5b95f", "DE-RISK": "#ea7c7c"}
EVENTS = (
    ("2020-02-20", "2020-04-30", "COVID shock 2020"),
    ("2022-01-03", "2022-10-31", "2022 inflation / rates repricing"),
    ("2024-08-01", "2024-08-12", "2024 yen-carry shock"),
)
FACTOR_GROUPS = (
    ("Market trend / drawdown", ("weak_20d_trend", "drawdown"), ("spx_close",),
     "The SPX trend and distance from its prior high"),
    ("Realized volatility / downside stress", ("realized_volatility",), ("spx_close",),
     "Recent SPX price swings"),
    ("Implied volatility", ("vix_level", "vix_acceleration"), ("vix_close",),
     "The level and recent movement of VIX"),
    ("Volatility term structure", ("front_vol_inversion", "vix_curve_inversion"),
     ("vix9d_close", "vix_close", "vix3m_close"),
     "Short- versus longer-dated volatility pricing"),
    ("Tail pricing", ("skew", "vvix"), ("skew_close", "vvix_close"),
     "Options tail and volatility-of-volatility pricing"),
)
OBSERVATION_LABELS = {
    "spx_close": "SPX",
    "vix_close": "VIX",
    "vix9d_close": "VIX9D",
    "vix3m_close": "VIX3M",
    "skew_close": "SKEW",
    "vvix_close": "VVIX",
}
DRIVER_LABELS = {
    "weak_20d_trend": "Recent SPX trend",
    "drawdown": "SPX drawdown",
    "realized_volatility": "Recent SPX swings",
    "vix_level": "VIX level",
    "vix_acceleration": "Recent VIX change",
    "front_vol_inversion": "Near-term volatility pricing",
    "vix_curve_inversion": "Volatility term structure",
    "skew": "Tail-option pricing",
    "vvix": "Volatility-of-volatility pricing",
}


def plain_drivers(raw: object, input_row: pd.Series) -> list[str]:
    """Translate only already-attributed, observed drivers; no new attribution."""
    from src.free_signal_view import observed_drivers

    result = []
    for item in observed_drivers(raw, input_row):
        name, _, detail = item.partition("=")
        if name in DRIVER_LABELS:
            result.append(
                f"{DRIVER_LABELS[name]} {'adds to' if 'raises stress' in detail else 'eases'} market stress."
            )
    return result[:3]


def observed_history(history: pd.DataFrame, canonical: pd.DataFrame) -> pd.DataFrame:
    """Only persisted, completed signal dates with an observed SPX close."""
    signals = history.loc[history["risk_signal"].isin(STATES), ["date", "risk_signal"]].copy()
    signals["date"] = pd.to_datetime(signals["date"])
    prices = canonical.loc[:, ["date", "spx_close"]].copy()
    prices["date"] = pd.to_datetime(prices["date"])
    observed = signals.merge(prices, on="date", how="inner", validate="one_to_one")
    observed["spx_close"] = pd.to_numeric(observed["spx_close"], errors="coerce")
    return observed.dropna(subset=["spx_close"]).sort_values("date").reset_index(drop=True)


def forward_returns(history: pd.DataFrame, canonical: pd.DataFrame) -> pd.DataFrame:
    """Five subsequent published-date SPX rows; refuse gaps or provisional outcomes."""
    if history.empty:
        return pd.DataFrame(columns=["date", "risk_signal", "forward_return"])
    last_published = pd.to_datetime(history["date"]).max()
    prices = canonical.loc[:, ["date", "spx_close"]].copy()
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.loc[prices["date"] <= last_published].sort_values("date").reset_index(drop=True)
    prices["spx_close"] = pd.to_numeric(prices["spx_close"], errors="coerce")
    # Do not bridge missing Yahoo closes: all six calendar rows must be observed.
    valid = prices["spx_close"].notna()
    for offset in range(1, 6):
        valid &= prices["spx_close"].shift(-offset).notna()
    prices["forward_return"] = (
        prices["spx_close"].shift(-5).div(prices["spx_close"]).sub(1).mul(100)
    )
    prices = prices.loc[valid, ["date", "forward_return"]]
    signals = history.loc[history["risk_signal"].isin(STATES), ["date", "risk_signal"]].copy()
    signals["date"] = pd.to_datetime(signals["date"])
    return signals.merge(prices, on="date", how="inner", validate="one_to_one").sort_values("date")


def return_summary(returns: pd.DataFrame) -> list[dict]:
    return [
        {
            "state": state,
            "count": int(len(group)),
            "median": float(group["forward_return"].median()) if len(group) else None,
            "downside": float(group["forward_return"].lt(0).mean() * 100) if len(group) else None,
        }
        for state in STATES
        for group in (returns.loc[returns["risk_signal"] == state],)
    ]


def factor_cards(components: list[dict], row: pd.Series) -> list[dict]:
    by_name = {item["name"]: item for item in components}
    cards = []
    for title, names, fields, description in FACTOR_GROUPS:
        present = [by_name[name] for name in names if name in by_name]
        observations = [
            f"{OBSERVATION_LABELS[field]} {float(row[field]):,.2f}"
            for field in fields if pd.notna(row.get(field))
        ]
        weight = sum(float(item["effective_weight"]) for item in present)
        score = (
            sum(float(item["weighted_points"]) for item in present) / weight
            if weight > 0 and observations else None
        )
        status = (
            "Unavailable" if score is None else
            "Supportive" if score <= 35 else
            "Stressed" if score >= 65 else "Neutral"
        )
        explanation = (
            "No verified real observation and score for this group."
            if score is None else
            f"{description} {'reduces' if status == 'Supportive' else 'adds to' if status == 'Stressed' else 'does not strongly shift'} the overall stress reading."
        )
        cards.append({
            "title": title, "status": status, "score": score,
            "observations": " · ".join(observations) if observations else "Unavailable",
            "explanation": explanation,
        })
    return cards


def regime_figure(observed: pd.DataFrame, window: str) -> go.Figure:
    if window != "MAX":
        months = {"1M": 1, "3M": 3, "1Y": 12}[window]
        observed = observed.loc[
            observed["date"] >= observed["date"].max() - pd.DateOffset(months=months)
        ].copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.83, 0.17],
                        vertical_spacing=0.035)
    fig.add_trace(go.Scatter(
        x=observed["date"], y=observed["spx_close"], mode="lines",
        line={"color": "#b5d7ed", "width": 2}, name="Observed SPX close",
        hovertemplate="%{x|%b %d, %Y}<br>SPX %{y:,.2f}<extra></extra>",
    ), row=1, col=1)
    # One bar per observed date: leave weekends and missing closes unclassified.
    midpoints = observed["date"] + timedelta(hours=12)
    for state in STATES:
        mask = observed["risk_signal"].eq(state)
        fig.add_trace(go.Bar(
            x=midpoints.loc[mask], y=[1] * int(mask.sum()),
            width=86_400_000, marker_color=COLORS[state],
            customdata=observed.loc[mask, "date"].dt.strftime("%Y-%m-%d"),
            name=LABELS[state], hovertemplate="%{customdata}<br>" + LABELS[state] + "<extra></extra>",
        ), row=2, col=1)
    for start, end, label in EVENTS:
        if pd.Timestamp(start) <= observed["date"].max() and pd.Timestamp(end) >= observed["date"].min():
            fig.add_vrect(x0=start, x1=end, fillcolor="#9aa8b4", opacity=0.11,
                          line_width=0, row=1, col=1,
                          annotation_text=label, annotation_position="top left",
                          annotation_font_size=9, annotation_font_color="#becbd5")
    fig.update_layout(
        barmode="overlay", bargap=0, height=330, margin=dict(l=4, r=4, t=34, b=8),
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#dbe5ed",
        legend=dict(orientation="h", y=-0.18, x=0, font_size=10),
        hovermode="closest",
    )
    fig.update_xaxes(showgrid=False, tickfont_size=10, nticks=5, row=2, col=1)
    fig.update_yaxes(title_text="SPX", tickfont_size=10, gridcolor="#273440", row=1, col=1)
    fig.update_yaxes(visible=False, range=[0, 1], row=2, col=1)
    return fig


def returns_figure(returns: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for state in STATES:
        subset = returns.loc[returns["risk_signal"] == state]
        fig.add_trace(go.Box(
            x=[LABELS[state]] * len(subset),
            y=subset["forward_return"], name=LABELS[state],
            marker_color=COLORS[state], line_color=COLORS[state],
            boxpoints="all", jitter=0.25, pointpos=0, marker_size=3,
            customdata=subset["date"].dt.strftime("%Y-%m-%d"),
            hovertemplate="Signal: %{customdata}<br>Next 5 observed SPX sessions: %{y:.2f}%<extra></extra>",
            showlegend=False,
        ))
    fig.add_hline(y=0, line_color="#8b9ba8", line_width=1)
    fig.update_layout(
        height=310, margin=dict(l=4, r=4, t=8, b=20),
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#dbe5ed",
        yaxis=dict(title="SPX return (%)", ticksuffix="%", gridcolor="#273440", tickfont_size=10),
        xaxis=dict(tickfont_size=10, tickangle=0),
    )
    return fig


def recent_cards(history: pd.DataFrame, canonical: pd.DataFrame) -> list[dict]:
    prices = canonical.set_index("date")
    result = []
    for _, item in history.tail(5).iloc[::-1].iterrows():
        date = session_date(item["date"])
        if date not in prices.index:
            continue
        observed = prices.loc[date]
        if pd.isna(observed.get("spx_close")):
            continue
        result.append({
            "date": date, "action": pm_action(item["risk_signal"]),
            "confidence": item.get("confidence") or "Unavailable",
            "tail": (tail_hedge_status(item.get("tail_risk_hazard_score"))
                     if has_real_tail_inputs(observed) else NO_TAIL),
        })
    return result