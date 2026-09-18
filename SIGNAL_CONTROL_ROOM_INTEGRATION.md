# Product Signal Control Room — read-only signal integration

## Operational API contract

The API reads the persisted real outputs under
`spx-flow-machine/data/free_signal`. It does not recalculate the model and does
not read synthetic intraday data.

All signal routes require:

```http
Authorization: Bearer <SIGNAL_API_TOKEN>
```

The token must be stored only in server-side secrets in both systems. The
Control Room browser must never receive it. Calls should be made by the Control
Room backend.

### Routes

- `GET /api/signals/latest`
- `GET /api/signals/history?start=YYYY-MM-DD&end=YYYY-MM-DD`
- `GET /api/signals/provenance`

History range bounds are inclusive. Responses set
`Cache-Control: private, no-store`.

Every response identifies the observations as:

```json
{
  "observation_mode": "historical_reconstruction",
  "live_recorded": false
}
```

The existing 4,146 rows are causal historical reconstructions. They are not a
log of signals captured live at each historical close.

## Integrity guarantees

Before returning data, the API:

1. verifies `signal_history.csv` against its stored SHA-256;
2. verifies the latest JSON observation against the final CSV observation;
3. validates response fields against the generated OpenAPI/Zod contract;
4. preserves `free_daily_regime_v1`, units, dates, quality, confidence and
   `NOT_CALIBRATED`;
5. returns no dummy options-flow data and performs no fill or probability
   conversion.

## Control Room configuration

Configure these values in the Control Room backend:

- `SIGNAL_API_BASE_URL`: the published base URL of this Replit application.
- `SIGNAL_API_TOKEN`: the same dedicated secret configured in this Replit.

Do not use the temporary `.replit.dev` preview URL as a production dependency.
Obtain the published URL after this application is published.

## Fail-closed behavior

- Missing server token: `503` with no signal data.
- Missing/invalid bearer token: `401` with no signal data.
- Invalid date range: `400`.
- Missing or checksum-invalid persisted files: `503` with no signal data.

## Pending external step

This repository cannot modify
`https://product-signal-control-room.juanandresserur.chatgpt.site`. Its backend
must be configured to call the routes above. No claim is made that the external
dashboard is already connected.