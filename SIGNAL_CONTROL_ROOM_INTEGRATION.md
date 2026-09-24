# Signal Hub integration — SPX Regime Machine

The public API is read-only and does not require login. Its OpenAPI contract is
`lib/api-spec/openapi.yaml` (`regime.signal.v3`); generated client and validators
come from that file. Configure Signal Hub with the **published** API base URL,
not a `.replit.dev` preview URL. The private Signal Hub backend is not in this
workspace; its actual integration remains unverified.

| Route | Meaning |
| --- | --- |
| `GET /api/capabilities` | Supported contract, PIT fields and pagination |
| `GET /api/signals/catalog` | Persisted models and date bounds |
| `GET /api/signals/latest` | **Operational only**: an eligible, fresh, registered live event; returns `503` with `NO_ELIGIBLE_LIVE_SIGNAL` when absent |
| `GET /api/signals/history` | Research history, including reconstructed signals; `start`, `end`, `as_of`, `model_version`, `limit`, `cursor` filters |
| `GET /api/signals/as-of?as_of=...` | Research history available by an ISO-8601 timestamp with timezone; dates and timestamps are strict |
| `GET /api/signals/provenance` | Source manifest, observed coverage, snapshot lineage and hashes |
| `GET /api/healthz` | Integrity, connectivity, source freshness, computation, persistence and Hub eligibility with blockers |

All signal responses use `Cache-Control: private, no-store`. Paginated history
is chronological by `(session_date, event_id)`; treat `next_cursor` as opaque.
Trust each row's `observation_mode`, `live_recorded`, `available_at`,
`computed_at`, `observation_at`, `valid_from`, `valid_until`, `freshness`,
`quality`, lineage and checksums. Do not infer past live observations from a
historical row's `market_as_of`. The 4,146 preserved
`free_daily_regime_v1` rows are **historical reconstructions**, never
live-registered signals; their IDs and payloads are unchanged. The v3
`contract_version` describes the response contract, not a re-key of those IDs.
Yahoo is research-only even after a successful post-close refresh. Scores are
not calibrated probabilities.

There is currently **no registered live data provider**. Signal Hub should
show unavailable/not ready when `/api/signals/latest` returns 503, while
allowing separate research history views. Never silently promote a history row
to an operational recommendation. A 200 health response with `status: STALE`
means historical reads work, **not** that operational latest is eligible.

## Scheduled refresh

The API is autoscaled and deliberately has no in-process timer. After building
the API, `pnpm --filter @workspace/api-server run refresh:once` is the
**one-shot** weekday-after-18:00 America/New_York refresh command. It stages
Yahoo research output and publishes verified events, metadata and run state
atomically; failed runs keep the last published snapshot. Supply a durable
external scheduler and a runtime containing this workspace, Python and the
required Python dependencies. No production scheduler is configured here.
Do not claim automated production refresh from the API deployment alone.

Publishing is a user action. Recheck production endpoints after publishing;
this document does not assert that the current workspace code has already
replaced an older deployed release.