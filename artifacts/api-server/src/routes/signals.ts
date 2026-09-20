import { Router, type IRouter } from "express";
import { latestSignal, querySignals, sourceProvenance, signalBounds } from "../lib/signalRepository";

const router: IRouter = Router();
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const date = (v: unknown) => typeof v === "string" && datePattern.test(v) ? v : undefined;

function publicRow(row: NonNullable<Awaited<ReturnType<typeof latestSignal>>>) {
  return {
    ...(row.signal as Record<string, unknown>),
    event_id: row.eventId, contract_version: row.contractVersion,
    session_date: row.sessionDate, market_as_of: row.marketAsOf.toISOString(),
    available_at: row.availableAt.toISOString(), computed_at: row.computedAt.toISOString(),
    source_retrieved_at: row.sourceRetrievedAt.toISOString(), model_version: row.modelVersion,
    input_data_snapshot_id: row.inputSnapshotId, signal_snapshot_id: row.signalSnapshotId,
    input_checksum: row.inputChecksum, signal_checksum: row.rowChecksum,
    row_checksum: row.rowChecksum, observation_mode: row.observationMode,
    live_recorded: row.liveRecorded,
  };
}

router.get("/capabilities", (_req, res) => {
  res.json({
    contract_version: "regime.signal.v2",
    observation_modes: ["LIVE_REGISTERED", "HISTORICAL_RECONSTRUCTION"],
    live_recorded: false,
    point_in_time_fields: [
      "event_id", "market_as_of", "available_at", "computed_at",
      "source_retrieved_at", "model_version", "input_data_snapshot_id",
      "signal_snapshot_id", "observation_mode", "live_recorded",
    ],
    ordering: ["session_date", "event_id"],
    filters: ["start", "end", "model_version", "as_of"],
    pagination: { cursor: "opaque stable cursor", default_limit: 100, min_limit: 1, max_limit: 1000 },
    freshness_sla: "Source state is reported by /healthz and /signals/provenance.",
  });
});

router.get("/signals/latest", async (req, res): Promise<void> => {
  try {
    const row = await latestSignal();
    if (!row) throw new Error("Signal database is unseeded.");
    const payload = {
      observation_mode: row.observationMode, live_recorded: row.liveRecorded,
      model_version: row.modelVersion, retrieved_at_utc: row.sourceRetrievedAt.toISOString(),
      data_snapshot_id: row.inputSnapshotId, data: publicRow(row),
    };
    res.json(payload);
  } catch (error) {
    req.log.error({ err: error }, "Failed to read latest signal");
    res.status(503).json({ error: "Signal database is unavailable or unseeded." });
  }
});

router.get("/signals/history", async (req, res): Promise<void> => {
  const start = date(req.query["start"]);
  const end = date(req.query["end"]);
  if ((req.query["start"] && !start) || (req.query["end"] && !end) || (start && end && start > end)) {
    res.status(400).json({ error: "start and end must be valid YYYY-MM-DD dates with start <= end." }); return;
  }
  const rawLimit = req.query["limit"];
  const limit = rawLimit === undefined ? 100 : Number(rawLimit);
  if (!Number.isInteger(limit) || limit < 1 || limit > 1000) {
    res.status(400).json({ error: "limit must be an integer between 1 and 1000." }); return;
  }
  const asOfRaw = req.query["as_of"];
  const asOf = asOfRaw ? new Date(String(asOfRaw)) : undefined;
  if (asOfRaw && (!asOf || Number.isNaN(asOf.getTime()))) {
    res.status(400).json({ error: "as_of must be an ISO datetime." }); return;
  }
  try {
    const result = await querySignals({
      start, end, limit, asOf, cursor: typeof req.query["cursor"] === "string" ? req.query["cursor"] : undefined,
      modelVersion: typeof req.query["model_version"] === "string" ? req.query["model_version"] : undefined,
    });
    const data = result.rows.map(publicRow);
    const payload = {
      observation_mode: "HISTORICAL_RECONSTRUCTION", live_recorded: false,
      model_version: typeof req.query["model_version"] === "string" ? req.query["model_version"] : (result.rows[0]?.modelVersion ?? ""),
      start: start ?? result.rows[0]?.sessionDate ?? "", end: end ?? result.rows.at(-1)?.sessionDate ?? "",
      count: data.length, total: result.total, data, next_cursor: result.nextCursor,
    };
    res.json(payload);
  } catch (error) {
    req.log.error({ err: error }, "Failed to read signal history");
    res.status(503).json({ error: "Signal database is unavailable or unseeded." });
  }
});

router.get("/signals/provenance", async (req, res): Promise<void> => {
  try {
    const source = await sourceProvenance();
    const manifest = source.manifest;
    const coverage = source.coverage["per_series"] as Record<string, Record<string, unknown>>;
    const series = manifest["series"] as Record<string, Record<string, unknown>> | undefined;
    const bounds = await signalBounds();
    const payload = {
      observation_mode: "HISTORICAL_RECONSTRUCTION", live_recorded: false,
      source: String(manifest["input_source"]), model_version: String(manifest["model_version"]),
      requested_start_date: String(manifest["requested_start_date"]), requested_end_date: String(manifest["requested_end_date"]),
      retrieved_at_utc: source.latest["retrieved_at_utc"], history_first_date: bounds.first,
      history_last_date: bounds.last, history_row_count: bounds.count,
      history_sha256: String(manifest["signal_history_sha256"]), input_data_snapshot_id: String(manifest["input_data_snapshot_id"]),
      signal_snapshot_id: String(manifest["signal_snapshot_id"]), probability_status: "NOT_CALIBRATED" as const,
      score_semantics: String(manifest["score_semantics"]),
      series: Object.entries(coverage).map(([field, value]) => ({
        field, ticker: String(value["ticker"]), source: String(series?.[field]?.["source"] ?? manifest["input_source"]),
        first_valid_date: String(value["first_valid_date"]), last_valid_date: String(value["last_valid_date"]),
        observations: Number(value["observations"]), raw_payload_sha256: String(series?.[field]?.["raw_payload_sha256"] ?? ""),
      })),
    };
    res.json(payload);
  } catch (error) {
    req.log.error({ err: error }, "Failed to read signal provenance");
    res.status(503).json({ error: "Signal database is unavailable or unseeded." });
  }
});
export default router;