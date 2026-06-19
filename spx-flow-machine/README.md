# SPX Flow Machine

> Options flow → directional pressure → 5m/15m forward returns

An offline research dashboard that simulates SPX options flow, classifies flow pressure, builds 1-minute features, labels forward returns, and evaluates whether high flow scores predict directional price moves.

---

## What the app does

1. **Generates synthetic data** — One trading day (09:30–16:00) of minute-level SPX price and options tick data with semi-realistic properties (open/close activity concentration, occasional large sweeps, injected weak predictive signal).
2. **Enriches trades** — Classifies each trade by size tier (small → block), aggression, and flow direction (bullish/bearish).
3. **Aggregates to 1-minute bars** — Computes notional breakdown (call buy/sell, put buy/sell), net delta, net gamma, sweep count, ATM share, short-DTE share, and total notional.
4. **Builds z-scored features** — Rolling 30-bar z-scores to normalize each feature, using only past data to avoid look-ahead bias.
5. **Labels forward returns** — Attaches 5m and 15m log-returns and binary direction labels to each bar.
6. **Scores flow** — Combines z-scored features into an interpretable scalar score (-10 to +10) with Bullish/Bearish/Neutral labels and Low/Medium/High confidence.
7. **Evaluates the signal** — Hit rates, average return by score bucket, long/short backtest with costs, daily Sharpe approximation, and max drawdown.
8. **Renders a dashboard** — Streamlit + Plotly charts with sidebar controls for threshold, horizon, cost, and random seed.

---

## What is dummy vs. real

| Component | Dummy (current) | Real (production) |
|---|---|---|
| SPX price path | Geometric Brownian motion + regime shocks | Databento continuous SPX futures or NBBO mid |
| Options trades | Synthetic tick generation | Databento OPRA trade feed (dataset: `opra.pillar`) |
| Delta / Gamma | Approximate heuristics | OptionMetrics surface or live model |
| Predictive signal | Artificially injected (SNR ≈ 0.3) | Empirically estimated from real data |
| DTE / Strike | Randomly sampled | Exact from OPRA symbology |

---

## How Databento OPRA would plug in

Replace `src/generate_dummy_data.py` with a Databento OPRA reader. The interface contract:

```python
# src/databento_loader.py (to be written)
import databento as db

def load_spx_price(date: str) -> pd.DataFrame:
    """
    Returns: DataFrame with columns [timestamp, spx_price]
    Use SPXW continuous NBBO mid or ESc1 futures price.
    """

def load_options_trades(date: str) -> pd.DataFrame:
    """
    Returns: DataFrame matching the dummy trade schema:
      timestamp, option_type, side, strike, dte, price,
      quantity, delta, gamma, notional, is_sweep, moneyness

    Steps:
    1. client = db.Historical(api_key=os.environ["DATABENTO_API_KEY"])
    2. data = client.timeseries.get_range(
           dataset="OPRA.PILLAR",
           schema="trades",
           symbols=["SPX"],
           start=f"{date}T09:30",
           end=f"{date}T16:00",
       )
    3. Parse MBP-1 or trades schema → map side from action field
    4. Attach greeks from your vol surface (OptionMetrics / local model)
    5. Compute notional = price * quantity * 100
    6. Classify is_sweep from exchange-flagged block/sweep condition codes
    """
```

Then in `app.py`, swap:
```python
# Before (dummy):
from src.generate_dummy_data import generate_spx_price, generate_options_trades

# After (real):
from src.databento_loader import load_spx_price as generate_spx_price
from src.databento_loader import load_options_trades as generate_options_trades
```

All downstream modules (`classify_trades`, `make_bars`, `build_features`, etc.) remain unchanged.

---

## Running the app

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## Project structure

```
spx-flow-machine/
├── app.py                    # Streamlit entry point
├── requirements.txt
├── README.md
├── data/                     # Output cache (future use)
└── src/
    ├── generate_dummy_data.py  # Synthetic data generator (replace with OPRA loader)
    ├── classify_trades.py      # Size tier, aggression, flow direction
    ├── make_bars.py            # Aggregate trades → 1-minute bars
    ├── build_features.py       # Rolling z-score normalization
    ├── label_returns.py        # 5m / 15m forward return labels
    ├── score_flow.py           # Flow score computation + direction labels
    ├── evaluate_signal.py      # Hit rates, bucketed returns, strategy PnL
    └── plots.py                # Plotly chart builders
```

---

## Main limitations

1. **Synthetic signal** — The injected predictive relationship (SNR ≈ 0.3) does not represent real SPX options flow predictability. Real options flow signal is much weaker and regime-dependent.
2. **No vol surface** — Delta/gamma are rough heuristics. Real greeks require a live implied vol surface calibrated to OPRA quotes.
3. **No NBBO** — Without quote data, we cannot identify whether a trade crossed the ask (aggressive buy) or hit the bid (aggressive sell). Real aggression classification requires NBBO at time of trade.
4. **No purging** — The backtest does not use purged cross-validation. Serial correlation in the score will inflate Sharpe estimates.
5. **Single day** — The current pipeline covers one intraday session. Real evaluation requires weeks/months of data with walk-forward validation.
6. **No overnight / events** — FOMC, CPI, and earnings produce anomalous flow regimes that need separate handling.

---

## Next steps

- [ ] **Replace dummy generator** with Databento OPRA trades + NBBO feed (see above)
- [ ] **Add real greeks** via OptionMetrics or an internal vol surface
- [ ] **Improve sweep detection** using OPRA condition codes and quote-spread crossing
- [ ] **Add ML model** — XGBoost / LightGBM on the z-scored features with purged k-fold CV
- [ ] **Walk-forward backtest** — Expanding window OOS evaluation over 30+ days
- [ ] **Regime conditioning** — Separate model for high-VIX vs. low-VIX environments
- [ ] **Alert system** — Push Slack/email when flow_score exceeds threshold in real time
- [ ] **Live feed** — Connect Databento WebSocket for real-time bar updates via `st.rerun()`
