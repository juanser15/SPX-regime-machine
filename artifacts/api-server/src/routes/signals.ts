import { Router, type IRouter } from "express";
import {
  CONTRACT_VERSION,
  operationalLatestSignal,
  querySignals,
  signalBounds,
  sourceProvenance,
} from "../lib/signalRepository";
import { GetLatestSignalResponse, GetSignalHistoryResponse, GetSignalAsOfResponse, GetSignalProvenanceResponse } from "@workspace/api-zod";

const router: IRouter = Router();
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const date = (value: unknown): string | undefined => {
  if (typeof value !== "string" || !datePattern.test(value)) return undefined;
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return undefined;
  return parsed.toISOString().slice(0, 10) === value ? value : undefined;
};
const isoDateTime = (value: unknown): Date | undefined => {
  if (typeof value !== "string") return undefined;
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  if (!parts) return undefined;
  const [, year, month, day, hour, minute, second, , offsetHour, offsetMinute] = parts;
  const days = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
  if (Number(month) < 1 || Number(month) > 12 || Number(day) < 1 || Number(day) > days ||
      Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59 ||
      Number(offsetHour ?? 0) > 23 || Number(offsetMinute ?? 0) > 59) return undefined;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed;
};
function cache(res: any) {
  res.set("Cache-Control", "private, no-store");
}
function error(res: any, status: number, code: string, message: string) {
  cache(res);
  res.status(status).json({ error: { code, message } });
}
function publicRow(row: any) {
  const required = ["revisionId", "observationAt", "validFrom", "validUntil", "ingestedAt", "sourceMode", "freshness", "quality", "providerLineage", "configChecksum", "dataChecksum", "provenance"];
  if (required.some((key) => row[key] === null || row[key] === undefined)) {
    throw new Error("Persisted signal row is incomplete.");
  }
  return {
    ...(row.signal as Record<string, unknown>),
    // Legacy rows retain their immutable v2 event identity, but the public
    // representation is always the current v3 response contract.
    event_id: row.eventId, contract_version: CONTRACT_VERSION,
    session_date: row.sessionDate, market_as_of: row.marketAsOf.toISOString(),
    available_at: row.availableAt.toISOString(), computed_at: row.computedAt.toISOString(),
    source_retrieved_at: row.sourceRetrievedAt.toISOString(), model_version: row.modelVersion,
    input_data_snapshot_id: row.inputSnapshotId, signal_snapshot_id: row.signalSnapshotId,
    input_checksum: row.inputChecksum, signal_checksum: row.rowChecksum,
    row_checksum: row.rowChecksum, observation_mode: row.observationMode,
    live_recorded: row.liveRecorded,
    revision_id: row.revisionId, observation_at: row.observationAt.toISOString(),
    valid_from: row.validFrom.toISOString(), valid_until: row.validUntil.toISOString(),
    ingested_at: row.ingestedAt.toISOString(), source_mode: row.sourceMode,
    freshness: row.freshness, quality: row.quality, provider_lineage: row.providerLineage,
    config_checksum: row.configChecksum, data_checksum: row.dataChecksum, provenance: row.provenance,
    research_only: row.observationMode === "HISTORICAL_RECONSTRUCTION",
  };
}
const send = (res: any, body: unknown) => { cache(res); res.json(body); };
const sendValidated = (res: any, schema: { parse: (value: unknown) => unknown }, body: unknown) => {
  // Generated Zod date coercions produce Date objects. Validate the wire
  // representation without serializing their transformed output: OpenAPI
  // format: date must remain YYYY-MM-DD on the wire.
  schema.parse(body);
  cache(res);
  res.json(body);
};

router.get("/capabilities", (_req, res) => send(res, {
  contract_version: CONTRACT_VERSION,
  observation_modes: ["LIVE_REGISTERED", "HISTORICAL_RECONSTRUCTION"],
  live_recorded: true,
  point_in_time_fields: ["event_id", "observation_at", "valid_from", "valid_until", "available_at", "computed_at", "ingested_at"],
  ordering: ["session_date", "event_id"],
  filters: ["start", "end", "model_version", "as_of", "cursor", "limit"],
  pagination: { cursor: "opaque stable cursor", default_limit: 100, min_limit: 1, max_limit: 1000 },
  freshness_sla: "72 hours",
}));

router.get("/signals/catalog", async (_req, res) => {
  try {
    const bounds = await signalBounds();
    const result = await querySignals({ limit: 1000 });
    const models = [...new Set(result.rows.map((row) => row.modelVersion))].map((model_version) => ({ model_version }));
    send(res, { contract_version: CONTRACT_VERSION, source: "persisted_signal_events", models, bounds });
  } catch { error(res, 503, "SIGNAL_DATA_UNAVAILABLE", "Signal catalog is unavailable."); }
});

async function history(req: any, res: any, forcedAsOf?: Date): Promise<void> {
  const start = date(req.query.start), end = date(req.query.end);
  if ((req.query.start !== undefined && !start) || (req.query.end !== undefined && !end) || (start && end && start > end)) {
    error(res, 400, "INVALID_DATE", "start and end must be real YYYY-MM-DD dates with start <= end."); return;
  }
  const rawLimit = req.query.limit;
  const limit = rawLimit === undefined ? 100 : Number(rawLimit);
  if (!Number.isInteger(limit) || limit < 1 || limit > 1000) { error(res, 400, "INVALID_LIMIT", "limit must be an integer between 1 and 1000."); return; }
  const asOf = forcedAsOf ?? (req.query.as_of === undefined ? undefined : isoDateTime(req.query.as_of));
  if (req.query.as_of !== undefined && !asOf) { error(res, 400, "INVALID_AS_OF", "as_of must be an ISO datetime with timezone."); return; }
  if (forcedAsOf === undefined && req.query.cursor !== undefined && typeof req.query.cursor !== "string") {
    error(res, 400, "INVALID_CURSOR", "cursor must be an opaque string."); return;
  }
  try {
    const result = await querySignals({
      start, end, limit, asOf,
      cursor: typeof req.query.cursor === "string" ? req.query.cursor : undefined,
      modelVersion: typeof req.query.model_version === "string" ? req.query.model_version : undefined,
    });
    const data = result.rows.map(publicRow);
    const modes = [...new Set(result.rows.map((row) => row.observationMode))];
    sendValidated(res, forcedAsOf ? GetSignalAsOfResponse : GetSignalHistoryResponse, {
      contract_version: CONTRACT_VERSION, observation_mode: modes.length === 1 ? modes[0] : "MIXED",
      live_recorded: result.rows.some((row) => row.liveRecorded),
      model_version: typeof req.query.model_version === "string" ? req.query.model_version : (result.rows[0]?.modelVersion ?? null),
      start: start ?? result.rows[0]?.sessionDate ?? null, end: end ?? result.rows.at(-1)?.sessionDate ?? null,
      as_of: asOf?.toISOString() ?? null, count: data.length, total: result.total, data, next_cursor: result.nextCursor ?? null,
    });
  } catch (caught) {
    if (caught instanceof Error && caught.message === "Invalid cursor.") { error(res, 400, "INVALID_CURSOR", caught.message); return; }
    if (caught instanceof Error && caught.message === "Persisted signal row is incomplete.") { error(res, 503, "INCOMPLETE_SIGNAL_ROW", caught.message); return; }
    error(res, 503, "SIGNAL_DATA_UNAVAILABLE", "Signal data is unavailable.");
  }
}

router.get("/signals/latest", async (_req, res) => {
  try {
    const row = await operationalLatestSignal();
    if (!row) { error(res, 503, "NO_ELIGIBLE_LIVE_SIGNAL", "No eligible live signal is available."); return; }
    sendValidated(res, GetLatestSignalResponse, { contract_version: CONTRACT_VERSION, observation_mode: row.observationMode, live_recorded: true,
      model_version: row.modelVersion, retrieved_at_utc: row.sourceRetrievedAt.toISOString(),
      data_snapshot_id: row.inputSnapshotId, data: publicRow(row) });
  } catch (caught) {
    if (caught instanceof Error && caught.message === "Persisted signal row is incomplete.") { error(res, 503, "INCOMPLETE_SIGNAL_ROW", caught.message); return; }
    error(res, 503, "SIGNAL_DATA_UNAVAILABLE", "Signal data is unavailable.");
  }
});
router.get("/signals/history", (req, res) => { void history(req, res); });
router.get("/signals/as-of", async (req, res) => {
  const asOf = isoDateTime(req.query.as_of);
  if (!asOf) { error(res, 400, "INVALID_AS_OF", "as_of is required and must be an ISO datetime with timezone."); return; }
  await history(req, res, asOf);
});

router.get("/signals/provenance", async (_req, res) => {
  try {
    const source = await sourceProvenance();
    const manifest = source.manifest as Record<string, unknown>;
    const requiredManifest = ["input_source", "model_version", "requested_start_date", "requested_end_date", "signal_history_sha256", "input_data_snapshot_id", "signal_snapshot_id", "score_semantics"];
    if (requiredManifest.some((key) => typeof manifest[key] !== "string" || !manifest[key])) throw new Error("Provenance manifest is incomplete.");
    const coverage = (source.coverage as Record<string, unknown> | undefined)?.["per_series"] as Record<string, Record<string, unknown>> | undefined;
    const dataManifest = source.dataManifest as Record<string, unknown> | undefined;
    const seriesManifest = dataManifest?.["series"] as Record<string, Record<string, unknown>> | undefined;
    const bounds = await signalBounds();
    const latest = source.latest as Record<string, unknown> | undefined;
    if (!bounds.first || !bounds.last || typeof latest?.["retrieved_at_utc"] !== "string") throw new Error("Provenance coverage is unavailable.");
    if (!coverage || !seriesManifest) throw new Error("Provenance series coverage is unavailable.");
    const coverageEntries = Object.entries(coverage);
    if (coverageEntries.length === 0 || coverageEntries.some(([field, value]) =>
      typeof value.ticker !== "string" || typeof value.first_valid_date !== "string" ||
      typeof value.last_valid_date !== "string" || !Number.isFinite(Number(value.observations)) ||
      typeof seriesManifest[field]?.raw_payload_sha256 !== "string" ||
      typeof seriesManifest[field]?.source !== "string",
    )) throw new Error("Provenance series lineage is incomplete.");
    const series = coverageEntries.map(([field, value]) => ({
      field, ticker: value.ticker, source: seriesManifest?.[field]?.source ?? manifest.input_source,
      first_valid_date: value.first_valid_date, last_valid_date: value.last_valid_date,
      observations: Number(value.observations), raw_payload_sha256: seriesManifest?.[field]?.raw_payload_sha256,
    }));
    sendValidated(res, GetSignalProvenanceResponse, { contract_version: CONTRACT_VERSION, observation_mode: "HISTORICAL_RECONSTRUCTION", live_recorded: false,
      source: manifest.input_source, model_version: manifest.model_version,
      requested_start_date: manifest.requested_start_date, requested_end_date: manifest.requested_end_date,
      retrieved_at_utc: latest["retrieved_at_utc"],
      history_first_date: bounds.first, history_last_date: bounds.last, history_row_count: bounds.count,
      history_sha256: manifest.signal_history_sha256, input_data_snapshot_id: manifest.input_data_snapshot_id,
      signal_snapshot_id: manifest.signal_snapshot_id, probability_status: "NOT_CALIBRATED",
      score_semantics: manifest.score_semantics,
      series,
    });
  } catch { error(res, 503, "SIGNAL_DATA_UNAVAILABLE", "Signal provenance is unavailable."); }
});
export default router;