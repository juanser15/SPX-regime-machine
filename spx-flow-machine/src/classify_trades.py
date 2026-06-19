"""
classify_trades.py
==================
Classify options trades by size tier, aggression, and other categorical attributes.

These classifiers enrich the raw trade DataFrame before aggregation into bars.
When replacing dummy data with Databento OPRA, apply the same classifiers to
real trades after parsing the tick feed.
"""

import pandas as pd
import numpy as np


LARGE_TRADE_NOTIONAL_THRESHOLD = 50_000
SWEEP_NOTIONAL_THRESHOLD = 100_000


def classify_trade_size(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a 'size_tier' column: 'small', 'medium', 'large', 'block'.

    Thresholds are notional-based (dollar value of the trade).
    """
    df = df.copy()
    conditions = [
        df["notional"] < 10_000,
        df["notional"] < 50_000,
        df["notional"] < 250_000,
    ]
    choices = ["small", "medium", "large"]
    df["size_tier"] = np.select(conditions, choices, default="block")
    return df


def classify_aggression(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add an 'aggressive' boolean column.

    A trade is considered aggressive if:
    - It is a sweep (is_sweep = True), OR
    - It is a large trade (notional > threshold) going buy-side on calls
      or sell-side on puts (i.e., directionally bullish pressure), OR
    - It is a large trade going sell-side on calls or buy-side on puts
      (directionally bearish pressure).

    For real OPRA data, use NBBO quote at time of trade to determine
    whether the trade crossed the ask (aggressive buy) or hit the bid
    (aggressive sell).
    """
    df = df.copy()
    df["aggressive"] = df["is_sweep"] | (df["notional"] >= LARGE_TRADE_NOTIONAL_THRESHOLD)
    return df


def add_flow_direction(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a 'flow_direction' column encoding directional pressure per trade.

    +1 = bullish pressure (call buy or put sell)
    -1 = bearish pressure (put buy or call sell)
     0 = ambiguous
    """
    df = df.copy()
    bullish = ((df["option_type"] == "call") & (df["side"] == "buy")) | (
        (df["option_type"] == "put") & (df["side"] == "sell")
    )
    bearish = ((df["option_type"] == "put") & (df["side"] == "buy")) | (
        (df["option_type"] == "call") & (df["side"] == "sell")
    )
    df["flow_direction"] = np.where(bullish, 1, np.where(bearish, -1, 0))
    return df


def enrich_trades(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply all trade classifiers in sequence.

    Parameters
    ----------
    df : pd.DataFrame
        Raw trades DataFrame (from generate_dummy_data or real OPRA parser).

    Returns
    -------
    pd.DataFrame
        Enriched trades with size_tier, aggressive, and flow_direction columns.
    """
    df = classify_trade_size(df)
    df = classify_aggression(df)
    df = add_flow_direction(df)
    return df
