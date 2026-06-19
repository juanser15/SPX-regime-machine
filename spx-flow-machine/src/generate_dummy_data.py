"""
generate_dummy_data.py
======================
Generates synthetic intraday SPX price path and options trades for one trading day.

The dummy data is structured to allow easy replacement with real Databento OPRA
tick data. The interface contract:
  - generate_spx_price(seed) -> pd.DataFrame with columns [timestamp, spx_price]
  - generate_options_trades(spx_df, seed) -> pd.DataFrame with the trade schema

Signals injected:
  - Aggressive call buying + put selling slightly predicts positive 5m SPX returns
  - Aggressive put buying + call selling slightly predicts negative 5m SPX returns
  - Signal is weak (SNR ~0.3) to keep it realistic
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta


MARKET_OPEN = datetime(2024, 1, 15, 9, 30)
MARKET_CLOSE = datetime(2024, 1, 15, 16, 0)
MINUTES_IN_DAY = int((MARKET_CLOSE - MARKET_OPEN).total_seconds() / 60)

SPX_BASE = 4800.0
SIGNAL_STRENGTH = 0.30


def _activity_weight(minute_idx: int, n_minutes: int) -> float:
    """
    Return a relative activity weight for a given minute index.
    Higher near open and close, with a midday lull.
    """
    x = minute_idx / n_minutes
    open_hump = 3.0 * np.exp(-((x - 0.0) ** 2) / (2 * 0.04**2))
    close_hump = 2.5 * np.exp(-((x - 1.0) ** 2) / (2 * 0.05**2))
    base = 0.5
    return base + open_hump + close_hump


def generate_spx_price(seed: int = 42) -> pd.DataFrame:
    """
    Generate a synthetic 1-minute SPX price path for one trading day.

    Returns
    -------
    pd.DataFrame
        Columns: timestamp (datetime), spx_price (float)
    """
    rng = np.random.default_rng(seed)
    timestamps = [MARKET_OPEN + timedelta(minutes=i) for i in range(MINUTES_IN_DAY + 1)]

    daily_drift = 0.0002
    vol_per_minute = 0.0008
    raw_returns = rng.normal(daily_drift / MINUTES_IN_DAY, vol_per_minute, MINUTES_IN_DAY)

    # Inject a few larger regime moves for realism
    for shock_minute in rng.choice(MINUTES_IN_DAY, size=4, replace=False):
        raw_returns[shock_minute] += rng.choice([-1, 1]) * rng.uniform(0.003, 0.007)

    prices = [SPX_BASE]
    for r in raw_returns:
        prices.append(prices[-1] * (1 + r))

    return pd.DataFrame({"timestamp": timestamps, "spx_price": prices})


def generate_options_trades(spx_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic SPX options trades for the trading day.

    The option trades have a weak directional signal embedded:
    - In minutes where future 5m SPX return > 0, more aggressive call buying
      and put selling is generated.
    - In minutes where future 5m SPX return < 0, more aggressive put buying
      and call selling is generated.

    Parameters
    ----------
    spx_df : pd.DataFrame
        Output of generate_spx_price().
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    pd.DataFrame
        One row per synthetic trade.
    """
    rng = np.random.default_rng(seed)
    trades = []

    n_minutes = len(spx_df) - 1

    for i in range(n_minutes):
        minute_ts = spx_df["timestamp"].iloc[i]
        spx_price = spx_df["spx_price"].iloc[i]

        # Compute future 5m return to embed weak signal
        future_idx = min(i + 5, n_minutes)
        future_price = spx_df["spx_price"].iloc[future_idx]
        fwd_ret = (future_price - spx_price) / spx_price

        activity = _activity_weight(i, n_minutes)
        n_trades = max(1, int(rng.poisson(lam=15 * activity)))

        # Sweep injection: higher chance near open/close
        sweep_prob = 0.05 + 0.10 * (activity > 1.5)

        for _ in range(n_trades):
            # Signal-driven call/put bias
            signal_bias = np.clip(fwd_ret * SIGNAL_STRENGTH * 500, -0.25, 0.25)
            call_prob = 0.50 + signal_bias

            option_type = "call" if rng.random() < call_prob else "put"

            # Aggressive side: if bullish signal → calls more likely bought, puts more likely sold
            if option_type == "call":
                buy_prob = 0.55 + signal_bias * 0.8
            else:
                buy_prob = 0.45 - signal_bias * 0.8
            buy_prob = np.clip(buy_prob, 0.1, 0.9)
            side = "buy" if rng.random() < buy_prob else "sell"

            # Strike selection
            moneyness_roll = rng.random()
            if moneyness_roll < 0.35:
                moneyness = "ATM"
                strike_offset = rng.integers(-5, 6) * 5
            elif moneyness_roll < 0.70:
                moneyness = "OTM"
                if option_type == "call":
                    strike_offset = rng.integers(1, 10) * 25
                else:
                    strike_offset = -rng.integers(1, 10) * 25
            else:
                moneyness = "ITM"
                if option_type == "call":
                    strike_offset = -rng.integers(1, 6) * 25
                else:
                    strike_offset = rng.integers(1, 6) * 25

            strike = round(spx_price + strike_offset, 0)

            # DTE distribution: heavy on 0–7 DTE (SPX weeklies)
            dte_roll = rng.random()
            if dte_roll < 0.45:
                dte = rng.integers(0, 3)
            elif dte_roll < 0.70:
                dte = rng.integers(3, 8)
            elif dte_roll < 0.88:
                dte = rng.integers(8, 31)
            else:
                dte = rng.integers(31, 120)

            # Option pricing (simplified Black-Scholes-like heuristic)
            intrinsic = max(0.0, (spx_price - strike) if option_type == "call" else (strike - spx_price))
            time_val = max(0.10, rng.normal(loc=5.0 + 0.15 * dte, scale=2.0))
            price = round(intrinsic + time_val, 2)

            # Greeks (approximate)
            delta_abs = rng.uniform(0.10, 0.90) if moneyness == "ATM" else rng.uniform(0.05, 0.45)
            delta = delta_abs if option_type == "call" else -delta_abs
            gamma = round(rng.uniform(0.0005, 0.005), 5)

            # Quantity: sweeps are larger
            is_sweep = rng.random() < sweep_prob
            if is_sweep:
                quantity = int(rng.integers(200, 1001))
            else:
                quantity = int(rng.integers(1, 50))

            notional = round(price * quantity * 100, 2)

            trades.append({
                "timestamp": minute_ts + timedelta(seconds=int(rng.integers(0, 60))),
                "minute": minute_ts,
                "option_type": option_type,
                "side": side,
                "strike": strike,
                "dte": int(dte),
                "price": price,
                "quantity": quantity,
                "delta": round(delta, 4),
                "gamma": gamma,
                "notional": notional,
                "is_sweep": is_sweep,
                "moneyness": moneyness,
            })

    df = pd.DataFrame(trades)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df
