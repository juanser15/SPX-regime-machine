import { Router, type IRouter } from "express";
import {
  GetLatestSignalResponse,
  GetSignalHistoryQueryParams,
  GetSignalHistoryResponse,
  GetSignalProvenanceResponse,
} from "@workspace/api-zod";
import { loadVerifiedSignals } from "../lib/signalStore";

const router: IRouter = Router();
const datePattern = /^\d{4}-\d{2}-\d{2}$/;

function parseDate(value: unknown): Date | null {
  if (typeof value !== "string" || !datePattern.test(value)) {
    return null;
  }
  const date = new Date(`${value}T00:00:00.000Z`);
  return Number.isNaN(date.getTime()) ||
    date.toISOString().slice(0, 10) !== value
    ? null
    : date;
}

router.get("/signals/latest", async (req, res): Promise<void> => {
  try {
    const store = await loadVerifiedSignals();
    const payload = {
      observation_mode: "historical_reconstruction" as const,
      live_recorded: false,
      model_version: String(store.latestMetadata["model_version"]),
      retrieved_at_utc: String(store.latestMetadata["retrieved_at_utc"]),
      data_snapshot_id: String(store.latestMetadata["data_snapshot_id"]),
      data: store.latest,
    };
    GetLatestSignalResponse.parse(payload);
    res.json(payload);
  } catch (error) {
    req.log.error({ err: error }, "Failed to read verified latest signal");
    res.status(503).json({ error: "Verified signal data is unavailable." });
  }
});

router.get("/signals/history", async (req, res): Promise<void> => {
  const start = parseDate(req.query["start"]);
  const end = parseDate(req.query["end"]);
  const parsed = GetSignalHistoryQueryParams.safeParse({ start, end });
  if (!start || !end || !parsed.success || start > end) {
    res.status(400).json({
      error: "start and end must be valid YYYY-MM-DD dates with start <= end.",
    });
    return;
  }

  try {
    const store = await loadVerifiedSignals();
    const startText = start.toISOString().slice(0, 10);
    const endText = end.toISOString().slice(0, 10);
    const data = store.history.filter(
      (observation) =>
        observation.date >= startText && observation.date <= endText,
    );
    const payload = {
      observation_mode: "historical_reconstruction" as const,
      live_recorded: false,
      model_version: String(store.latestMetadata["model_version"]),
      start: startText,
      end: endText,
      count: data.length,
      data,
    };
    GetSignalHistoryResponse.parse(payload);
    res.json(payload);
  } catch (error) {
    req.log.error({ err: error }, "Failed to read verified signal history");
    res.status(503).json({ error: "Verified signal data is unavailable." });
  }
});

router.get("/signals/provenance", async (req, res): Promise<void> => {
  try {
    const store = await loadVerifiedSignals();
    const perSeries = store.coverage["per_series"] as Record<
      string,
      Record<string, unknown>
    >;
    const manifestSeries = store.dataManifest["series"] as Record<
      string,
      Record<string, unknown>
    >;
    const payload = {
      observation_mode: "historical_reconstruction" as const,
      live_recorded: false,
      source: String(store.signalManifest["input_source"]),
      model_version: String(store.signalManifest["model_version"]),
      requested_start_date: String(
        store.signalManifest["requested_start_date"],
      ),
      requested_end_date: String(store.signalManifest["requested_end_date"]),
      retrieved_at_utc: String(store.latestMetadata["retrieved_at_utc"]),
      history_first_date: store.history[0]?.date,
      history_last_date: store.history.at(-1)?.date,
      history_row_count: store.history.length,
      history_sha256: String(store.signalManifest["signal_history_sha256"]),
      input_data_snapshot_id: String(
        store.signalManifest["input_data_snapshot_id"],
      ),
      signal_snapshot_id: String(store.signalManifest["signal_snapshot_id"]),
      probability_status: "NOT_CALIBRATED" as const,
      score_semantics: String(store.signalManifest["score_semantics"]),
      series: Object.entries(perSeries).map(([field, coverage]) => ({
        field,
        ticker: String(coverage["ticker"]),
        source: String(manifestSeries[field]?.["source"]),
        first_valid_date: String(coverage["first_valid_date"]),
        last_valid_date: String(coverage["last_valid_date"]),
        observations: Number(coverage["observations"]),
        raw_payload_sha256: String(
          manifestSeries[field]?.["raw_payload_sha256"],
        ),
      })),
    };
    GetSignalProvenanceResponse.parse(payload);
    res.json(payload);
  } catch (error) {
    req.log.error({ err: error }, "Failed to read signal provenance");
    res.status(503).json({ error: "Verified signal data is unavailable." });
  }
});

export default router;