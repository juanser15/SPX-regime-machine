"""
label_returns.py
================
Compute forward return labels for each 1-minute bar.

Labels are computed from the SPX price path: ret_5m and ret_15m are the
log-returns from the current bar close to 5 or 15 bars later.

In a real-time system, replace spx_price with the NBBO mid at bar close
derived from the live Databento feed.
"""

import numpy as np
import pandas as pd


def label_returns(bars: pd.DataFrame, horizons: tuple = (5, 15)) -> pd.DataFrame:
    """
    Add forward return and binary direction labels to the bars DataFrame.

    For each horizon h in horizons, adds:
    - ret_{h}m  : log return over next h minutes
    - direction_{h}m : 1 if ret > 0, else 0

    Parameters
    ----------
    bars : pd.DataFrame
        Flow bars with at minimum a 'spx_price' column.
    horizons : tuple of int
        Forward horizons in minutes.

    Returns
    -------
    pd.DataFrame
        Bars with forward-return label columns appended.
        Rows where future price is unavailable will have NaN returns.
    """
    df = bars.copy()
    prices = df["spx_price"].values

    for h in horizons:
        future_prices = np.full(len(prices), np.nan)
        future_prices[:-h] = prices[h:]

        log_returns = np.where(
            ~np.isnan(future_prices),
            np.log(future_prices / np.where(prices > 0, prices, np.nan)),
            np.nan,
        )

        df[f"ret_{h}m"] = log_returns
        df[f"direction_{h}m"] = np.where(log_returns > 0, 1, np.where(log_returns < 0, 0, np.nan))

    return df
