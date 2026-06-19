"""
score_flow.py
=============
Compute the interpretable SPX options flow score.

Score formula (each term is already z-scored via build_features.py):

  flow_score =
      + z(call_buy_notional)       # bullish: aggressive call buying
      - z(call_sell_notional)      # bearish pressure removed
      - z(put_buy_notional)        # bearish: put buying
      + z(put_sell_notional)       # bullish: put selling (dealer hedges → buy pressure)
      + z(net_delta_notional)      # net bullish delta
      + 0.5 * z(sweep_count)       # urgency / conviction
      + 0.5 * z(atm_flow_share)    # ATM flow = directional, not hedging
      + 0.5 * z(short_dte_flow_share)  # short-DTE = gamma risk / directional

Score is then normalized to approximately [-10, +10].

Direction labels:
  flow_score > +2  → Bullish
  flow_score < -2  → Bearish
  else             → Neutral

Confidence levels:
  |score| < 3   → Low
  |score| < 6   → Medium
  |score| >= 6  → High
"""

import numpy as np
import pandas as pd


SCORE_SCALE = 10.0
BULLISH_THRESHOLD = 2.0
BEARISH_THRESHOLD = -2.0


def compute_flow_score(bars: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the flow score and add classification columns.

    Requires z-scored feature columns from build_features.build_features().

    Parameters
    ----------
    bars : pd.DataFrame
        Bars with z_{feature} columns.

    Returns
    -------
    pd.DataFrame
        Bars with flow_score_raw, flow_score, flow_direction, and
        flow_confidence columns appended.
    """
    df = bars.copy()

    def _get(col: str) -> pd.Series:
        return df.get(f"z_{col}", pd.Series(np.zeros(len(df)), index=df.index))

    raw = (
        +_get("call_buy_notional")
        - _get("call_sell_notional")
        - _get("put_buy_notional")
        + _get("put_sell_notional")
        + _get("net_delta_notional")
        + 0.5 * _get("sweep_count")
        + 0.5 * _get("atm_flow_share")
        + 0.5 * _get("short_dte_flow_share")
    )

    df["flow_score_raw"] = raw

    # Normalize to [-10, +10] using the empirical 95th percentile
    p95 = raw.abs().quantile(0.95)
    scale_factor = SCORE_SCALE / p95 if p95 > 0 else 1.0
    df["flow_score"] = (raw * scale_factor).clip(-SCORE_SCALE, SCORE_SCALE).round(2)

    df["flow_direction"] = pd.cut(
        df["flow_score"],
        bins=[-np.inf, BEARISH_THRESHOLD, BULLISH_THRESHOLD, np.inf],
        labels=["Bearish", "Neutral", "Bullish"],
    )

    abs_score = df["flow_score"].abs()
    df["flow_confidence"] = pd.cut(
        abs_score,
        bins=[-np.inf, 3.0, 6.0, np.inf],
        labels=["Low", "Medium", "High"],
    )

    return df
