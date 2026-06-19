"""
build_features.py
=================
Build model-ready feature columns from 1-minute flow bars.

Features are z-scored using a rolling window to avoid look-ahead bias.
All z-scores use only past data (expanding or rolling window).

For a production pipeline, replace the rolling z-score with an online
normalization layer that updates incrementally as new OPRA ticks arrive.
"""

import pandas as pd
import numpy as np


ROLLING_WINDOW = 30
MIN_PERIODS = 10

FEATURE_COLS = [
    "call_buy_notional",
    "call_sell_notional",
    "put_buy_notional",
    "put_sell_notional",
    "net_delta_notional",
    "sweep_count",
    "atm_flow_share",
    "short_dte_flow_share",
]


def rolling_zscore(series: pd.Series, window: int = ROLLING_WINDOW, min_periods: int = MIN_PERIODS) -> pd.Series:
    """
    Compute a rolling z-score that uses only past observations.

    Parameters
    ----------
    series : pd.Series
    window : int
        Rolling window length in bars.
    min_periods : int
        Minimum observations required to compute z-score.

    Returns
    -------
    pd.Series
        Z-scored series with NaN for insufficient history.
    """
    rolling_mean = series.rolling(window=window, min_periods=min_periods).mean()
    rolling_std = series.rolling(window=window, min_periods=min_periods).std()
    z = (series - rolling_mean) / rolling_std.replace(0, np.nan)
    return z.fillna(0.0)


def build_features(bars: pd.DataFrame) -> pd.DataFrame:
    """
    Add z-scored feature columns to the bars DataFrame.

    Column naming convention: z_{feature_name}

    Parameters
    ----------
    bars : pd.DataFrame
        Output of make_bars.aggregate_to_bars().

    Returns
    -------
    pd.DataFrame
        Bars with additional z_{feature} columns appended.
    """
    df = bars.copy()

    for col in FEATURE_COLS:
        if col in df.columns:
            df[f"z_{col}"] = rolling_zscore(df[col])
        else:
            df[f"z_{col}"] = 0.0

    return df
