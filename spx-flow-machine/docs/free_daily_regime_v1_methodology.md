# free_daily_regime_v1 — frozen daily research signal

**Scope.** This is a causal research classification of observed Yahoo Finance *daily* closes, not an executable live signal, probability, hedge recommendation, backtest, or options-flow measurement. The input session date is `date`; downloaded historical bars are only known to this system at `source_retrieved_at_utc`. A same-day Yahoo bar may be provisional. The UI withholds a current action until six hours after 16:00 New York, if the snapshot is over 72 hours old, or if that session lacks an SPX close; it does **not** retune the stored model classification.

## Inputs and transformations (all from the same immutable Yahoo snapshot)

| Component | Transformation of observed daily closes | Within-group base weight |
| --- | --- | ---: |
| Body: `weak_20d_trend` | `- (^GSPC close / ^GSPC close 20 rows earlier - 1)` | 0.25 |
| Body: `drawdown` | `- (^GSPC close / rolling 252-row maximum ^GSPC close - 1)`; maximum requires at least 20 observations | 0.25 |
| Body: `realized_volatility` | Standard deviation (sample, pandas default) of 20 consecutive one-row SPX returns, × √252 | 0.20 |
| Body: `vix_level` | `^VIX close` | 0.20 |
| Body: `vix_acceleration` | `^VIX close / ^VIX close 5 rows earlier - 1` | 0.10 |
| Tail: `skew` | `^SKEW close` | 0.30 |
| Tail: `vvix` | `^VVIX close` | 0.30 |
| Tail: `front_vol_inversion` | `^VIX9D close / ^VIX close` | 0.20 |
| Tail: `vix_curve_inversion` | `^VIX close / ^VIX3M close` | 0.20 |

SPX one-row return uses `pct_change(fill_method=None)`: no forward fill. Other 5/60-row SPX returns, MA20 gap and realized volatility at 10/60 rows are calculated as research features but **do not contribute** to this v1 score. “Rows” refer to ordered dates in the outer-joined observed calendar, not interpolated trading sessions.

For **each** transformed component on date *t*: over its trailing 252 rows including *t*, require at least 60 finite transformed values and a finite current value. The empirical percentile is `100 × count(finite values <= current value) / count(finite values)` (ties included). There is no look-ahead, fit over the full sample, interpolation, or synthetic substitute.

Available body components are averaged with their listed weights **renormalized over the components present at t**; same for tail. If a tail score exists, overall stress = `0.75 × body + 0.25 × tail`; otherwise overall = body. Without body, no score/signal is persisted. `effective_weight` in the audit is the normalized within-group weight multiplied by the overall group share; `weighted_points = percentile_score × effective_weight`, and their sum is the overall score. Driver strings rank the three available percentile components furthest from 50, with deterministic alphabetical tie-breaking. A missing optional series remains null and reduces available components; a failed required-series download fails explicitly rather than inventing values.

**Frozen decision bands:** `overall ≤ 35` → stored `RISK-ON`, displayed RISK-ON; `35 < overall < 65` → stored `NEUTRAL`, displayed **HOLD / NO ACTION**; `overall ≥ 65` → stored `DE-RISK`, displayed DE-RISK. These are empirical stress bands, **NOT CALIBRATED PROBABILITIES**. Confidence score = `0.65 × min(100, 2 × |overall - 50|) + 0.35 × 100 × (available components / 9)`. Confidence labels: HIGH ≥70, MEDIUM ≥45, otherwise LOW. Quality is COMPLETE only if every close is present on that session; otherwise DEGRADED_MISSING_INPUTS.

## Persistence and timing

The legacy `signal_history.csv`, `latest_signal.json`, and their immutable SHA-256 snapshot retain their original structure for existing consumers. A separate immutable JSONL sidecar at `data/free_signal/audits/<signal_snapshot_id>.jsonl` records each row under the [machine-readable schema](free_daily_regime_v1.schema.json): as-of session, UTC calculation/source-retrieval/available-at timestamps, source and input/signal snapshot IDs, exact action and scores, component percentiles/weights/contributions, confidence, quality, missing inputs, and drivers. `available_at_utc` is the **maximum** of New York market close + 6 hours, Yahoo retrieval, and computation; it does not pretend retrospectively reconstructed signals were available in the past. A rerun of the *same immutable* snapshot recreates the identical audit; an attempted refresh that changes any prior CSV observation is rejected rather than silently revising historical research. Source corrections require an explicit future revision policy, outside this gate.