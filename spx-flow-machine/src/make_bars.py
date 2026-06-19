"""
make_bars.py
============
Aggregate enriched options trades into 1-minute OHLCV-style flow bars.

Each bar represents all options activity in one minute and is keyed by the
bar's open timestamp (i.e., the minute boundary).

For real OPRA data, pass the enriched trade DataFrame through the same
aggregate_to_bars() function — the interface is identical.
"""

import pandas as pd
import numpy as np


def aggregate_to_bars(trades: pd.DataFrame, spx_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate per-trade data into 1-minute bars.

    Parameters
    ----------
    trades : pd.DataFrame
        Enriched trades (output of classify_trades.enrich_trades).
    spx_df : pd.DataFrame
        SPX price path with columns [timestamp, spx_price].

    Returns
    -------
    pd.DataFrame
        One row per minute with all flow aggregates and the SPX close price.
    """
    df = trades.copy()
    df["minute"] = df["timestamp"].dt.floor("min")

    grouped = df.groupby("minute")

    def _safe_sum(x):
        return x.sum() if len(x) > 0 else 0.0

    bars = []
    spx_minute_map = spx_df.set_index("timestamp")["spx_price"].to_dict()

    for minute, group in grouped:
        calls = group[group["option_type"] == "call"]
        puts = group[group["option_type"] == "put"]

        call_buys = calls[calls["side"] == "buy"]
        call_sells = calls[calls["side"] == "sell"]
        put_buys = puts[puts["side"] == "buy"]
        put_sells = puts[puts["side"] == "sell"]

        call_buy_notional = _safe_sum(call_buys["notional"])
        call_sell_notional = _safe_sum(call_sells["notional"])
        put_buy_notional = _safe_sum(put_buys["notional"])
        put_sell_notional = _safe_sum(put_sells["notional"])
        total_notional = call_buy_notional + call_sell_notional + put_buy_notional + put_sell_notional

        net_delta_notional = _safe_sum(group["delta"] * group["notional"])
        net_gamma_notional = _safe_sum(group["gamma"] * group["notional"])

        call_notional = call_buy_notional + call_sell_notional
        put_notional = put_buy_notional + put_sell_notional
        put_call_ratio = (put_notional / call_notional) if call_notional > 0 else np.nan

        sweep_count = int(group["is_sweep"].sum())

        atm_notional = _safe_sum(group.loc[group["moneyness"] == "ATM", "notional"])
        atm_flow_share = (atm_notional / total_notional) if total_notional > 0 else 0.0

        short_dte_notional = _safe_sum(group.loc[group["dte"] <= 7, "notional"])
        short_dte_flow_share = (short_dte_notional / total_notional) if total_notional > 0 else 0.0

        large_trade_count = int((group["notional"] >= 50_000).sum())

        spx_price = spx_minute_map.get(minute, np.nan)

        bars.append({
            "minute": minute,
            "spx_price": spx_price,
            "call_buy_notional": call_buy_notional,
            "call_sell_notional": call_sell_notional,
            "put_buy_notional": put_buy_notional,
            "put_sell_notional": put_sell_notional,
            "net_delta_notional": net_delta_notional,
            "net_gamma_notional": net_gamma_notional,
            "put_call_ratio_dollars": put_call_ratio,
            "sweep_count": sweep_count,
            "atm_flow_share": atm_flow_share,
            "short_dte_flow_share": short_dte_flow_share,
            "large_trade_count": large_trade_count,
            "total_notional": total_notional,
            "trade_count": len(group),
        })

    bars_df = pd.DataFrame(bars).sort_values("minute").reset_index(drop=True)
    bars_df["put_call_ratio_dollars"] = bars_df["put_call_ratio_dollars"].fillna(1.0)
    return bars_df
