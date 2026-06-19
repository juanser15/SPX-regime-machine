"""
evaluate_signal.py
==================
Evaluate whether the flow score predicts forward SPX returns.

Computes:
- Hit rate (directional accuracy) for Bullish / Bearish signals
- Average forward return by score decile bucket
- Long/short strategy PnL with transaction costs
- Daily Sharpe approximation
- Maximum drawdown
"""

import numpy as np
import pandas as pd


SCORE_BUCKETS = [-10, -6, -4, -2, 0, 2, 4, 6, 10]
BUCKET_LABELS = ["<-6", "-6:-4", "-4:-2", "-2:0", "0:2", "2:4", "4:6", ">6"]


def compute_hit_rates(df: pd.DataFrame, horizon: str = "5m") -> dict:
    """
    Compute directional hit rates by flow direction label.

    Parameters
    ----------
    df : pd.DataFrame
        Scored bars with flow_direction and direction_{horizon} columns.
    horizon : str
        '5m' or '15m'.

    Returns
    -------
    dict
        Keys: 'bullish_hit_rate', 'bearish_hit_rate', 'bullish_n', 'bearish_n'
    """
    label_col = f"direction_{horizon}"
    valid = df.dropna(subset=[label_col, "flow_direction"])

    bullish = valid[valid["flow_direction"] == "Bullish"]
    bearish = valid[valid["flow_direction"] == "Bearish"]

    bullish_hit = bullish[label_col].mean() if len(bullish) > 0 else np.nan
    bearish_hit = (1 - bearish[label_col]).mean() if len(bearish) > 0 else np.nan

    return {
        "bullish_hit_rate": round(bullish_hit * 100, 1) if not np.isnan(bullish_hit) else np.nan,
        "bearish_hit_rate": round(bearish_hit * 100, 1) if not np.isnan(bearish_hit) else np.nan,
        "bullish_n": len(bullish),
        "bearish_n": len(bearish),
    }


def average_return_by_bucket(df: pd.DataFrame, horizon: str = "5m") -> pd.DataFrame:
    """
    Compute average forward return by flow score bucket.

    Parameters
    ----------
    df : pd.DataFrame
    horizon : str
        '5m' or '15m'.

    Returns
    -------
    pd.DataFrame
        Columns: bucket, avg_return, count, hit_rate
    """
    ret_col = f"ret_{horizon}"
    dir_col = f"direction_{horizon}"
    valid = df.dropna(subset=[ret_col, "flow_score"])

    valid = valid.copy()
    valid["bucket"] = pd.cut(valid["flow_score"], bins=SCORE_BUCKETS, labels=BUCKET_LABELS)

    result = (
        valid.groupby("bucket", observed=True)
        .agg(
            avg_return=(ret_col, "mean"),
            count=(ret_col, "count"),
            hit_rate=(dir_col, "mean"),
        )
        .reset_index()
    )
    result["avg_return_bps"] = (result["avg_return"] * 10000).round(1)
    result["hit_rate_pct"] = (result["hit_rate"] * 100).round(1)
    return result


def run_strategy(
    df: pd.DataFrame,
    threshold: float = 3.0,
    cost_bps: float = 1.0,
    horizon: str = "5m",
) -> pd.DataFrame:
    """
    Simulate a simple long/short strategy based on flow score threshold.

    Rules:
    - flow_score > threshold  → long SPX for next {horizon} minutes
    - flow_score < -threshold → short SPX for next {horizon} minutes
    - otherwise               → flat

    Parameters
    ----------
    df : pd.DataFrame
    threshold : float
        Score threshold for entering a trade.
    cost_bps : float
        One-way cost per trade in basis points.
    horizon : str
        '5m' or '15m'.

    Returns
    -------
    pd.DataFrame
        Strategy output with position, gross_pnl, net_pnl, cum_pnl columns.
    """
    ret_col = f"ret_{horizon}"
    valid = df.dropna(subset=[ret_col, "flow_score"]).copy()

    valid["position"] = np.where(
        valid["flow_score"] > threshold, 1,
        np.where(valid["flow_score"] < -threshold, -1, 0)
    )

    valid["gross_pnl"] = valid["position"] * valid[ret_col]
    cost_per_trade = cost_bps / 10_000
    position_changes = valid["position"].diff().abs().fillna(0)
    valid["transaction_cost"] = position_changes * cost_per_trade
    valid["net_pnl"] = valid["gross_pnl"] - valid["transaction_cost"]
    valid["cum_pnl"] = valid["net_pnl"].cumsum()

    return valid


def compute_sharpe(strategy_df: pd.DataFrame) -> float:
    """
    Approximate daily Sharpe ratio from per-trade minute returns.

    Uses only bars where a position was taken.
    Annualization: sqrt(252 * 390) for minute bars.
    """
    active = strategy_df[strategy_df["position"] != 0]["net_pnl"]
    if len(active) < 2:
        return np.nan
    mean_ret = active.mean()
    std_ret = active.std()
    if std_ret == 0:
        return np.nan
    ann_factor = np.sqrt(252 * 390)
    return round(mean_ret / std_ret * ann_factor, 2)


def compute_max_drawdown(cum_pnl: pd.Series) -> float:
    """Compute maximum drawdown from a cumulative PnL series."""
    if len(cum_pnl) == 0:
        return 0.0
    running_max = cum_pnl.cummax()
    drawdown = cum_pnl - running_max
    return round(float(drawdown.min()) * 10_000, 1)


def full_evaluation(
    df: pd.DataFrame,
    threshold: float = 3.0,
    cost_bps: float = 1.0,
    horizon: str = "5m",
) -> dict:
    """
    Run full pipeline evaluation and return a summary dict.

    Returns
    -------
    dict
        hit_rates, bucket_table, strategy_df, sharpe, max_drawdown_bps,
        total_pnl_bps, n_trades
    """
    hit_rates = compute_hit_rates(df, horizon)
    bucket_table = average_return_by_bucket(df, horizon)
    strategy_df = run_strategy(df, threshold=threshold, cost_bps=cost_bps, horizon=horizon)

    sharpe = compute_sharpe(strategy_df)
    max_dd = compute_max_drawdown(strategy_df["cum_pnl"])
    total_pnl_bps = round(float(strategy_df["cum_pnl"].iloc[-1]) * 10_000, 1) if len(strategy_df) > 0 else 0.0
    n_trades = int((strategy_df["position"] != 0).sum())

    return {
        "hit_rates": hit_rates,
        "bucket_table": bucket_table,
        "strategy_df": strategy_df,
        "sharpe": sharpe,
        "max_drawdown_bps": max_dd,
        "total_pnl_bps": total_pnl_bps,
        "n_trades": n_trades,
    }
