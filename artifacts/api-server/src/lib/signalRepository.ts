import { createHash } from "node:crypto";
import { and, asc, desc, eq, gt, isNull, lt, lte, or, sql } from "drizzle-orm";
import { db, pool } from "@workspace/db";
import { signalEvents, signalIngestionRuns, signalSourceState } from "@workspace/db/schema";
import { loadVerifiedSignals, loadVerifiedSignalsFrom } from "./signalStore";
import type {
  IngestionRun,
  SignalSchedulerRepository,
  SourceState,
} from "./signalScheduler";

export const CONTRACT_VERSION = "regime.signal.v3";
// Identity of the original artifact is immutable. Its payload contract was
// v2, so changing the metadata contract must never re-key those 4,146 rows.
const EVENT_ID_CONTRACT_VERSION = "regime.signal.v2";
const SOURCE = "yahoo_daily";
const FRESHNESS_SLA_MS = 72 * 3_600_000;
let normalizationComplete = false;

function digest(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

export function deterministicEventId(input: {
  modelVersion: string;
  sessionDate: string;
  inputSnapshotId: string;
}): string {
  return digest([
    EVENT_ID_CONTRACT_VERSION,
    input.modelVersion,
    input.sessionDate,
    input.inputSnapshotId,
  ]);
}

function marketClose(date: string): Date {
  // Determine the New York offset at the session date (including DST).
  const probe = new Date(`${date}T16:00:00Z`);
  const hour = Number(new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", hour: "2-digit", hour12: false,
  }).format(probe));
  const offset = hour === 12 ? "-04:00" : "-05:00";
  return new Date(`${date}T16:00:00${offset}`);
}

function asDate(value: unknown): Date {
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) throw new Error("Artifact timestamp is invalid.");
  return date;
}

async function seedIfEmpty(): Promise<void> {
  const [{ count }] = await db.select({ count: sql<number>`count(*)` }).from(signalEvents);
  if (Number(count) > 0) {
    if (normalizationComplete) return;
    const candidates = await db.select().from(signalEvents).where(or(
      isNull(signalEvents.revisionId), isNull(signalEvents.observationAt),
      isNull(signalEvents.validUntil), isNull(signalEvents.configChecksum),
      isNull(signalEvents.sourceMode), isNull(signalEvents.dataChecksum),
      isNull(signalEvents.ingestedAt), isNull(signalEvents.validFrom),
      isNull(signalEvents.quality),
      sql`${signalEvents.availableAt} < greatest(${signalEvents.computedAt}, ${signalEvents.sourceRetrievedAt}, ((${signalEvents.sessionDate})::date + time '16:00' at time zone 'America/New_York') + interval '6 hours')`,
      isNull(signalEvents.provenance),
      sql`${signalEvents.observationMode} = 'LIVE_REGISTERED' and
        ((${signalEvents.providerLineage} is null) or ${signalEvents.providerLineage}->>'provider' in ('yahoo','yahoo_daily'))`,
    ));
    if (candidates.length > 0) await db.transaction(async (tx) => {
      for (const row of candidates) {
        const market = marketClose(row.sessionDate);
        const availableMs = Math.max(row.availableAt.getTime(), row.computedAt.getTime(),
          row.sourceRetrievedAt.getTime(), market.getTime() + 6 * 3600_000);
        const provider = row.providerLineage as Record<string, unknown> | null;
        const yahoo = row.observationMode === "HISTORICAL_RECONSTRUCTION" ||
          (row.observationMode === "LIVE_REGISTERED" &&
            (!provider || ["yahoo", "yahoo_daily"].includes(String(provider["provider"]))));
        await tx.update(signalEvents).set({
          availableAt: new Date(availableMs),
          revisionId: row.revisionId ?? row.signalSnapshotId,
          observationAt: row.observationAt ?? row.sourceRetrievedAt,
          sourceMode: yahoo ? "HISTORICAL_RECONSTRUCTION" : (row.sourceMode ?? row.observationMode),
          ingestedAt: row.ingestedAt ?? row.sourceRetrievedAt,
          validFrom: new Date(Math.max(row.validFrom?.getTime() ?? 0, availableMs)),
          validUntil: new Date(availableMs + 72 * 3600_000),
          quality: row.quality ?? "VERIFIED",
          providerLineage: row.providerLineage ?? { provider: "yahoo", mode: "HISTORICAL_RECONSTRUCTION" },
          configChecksum: row.configChecksum ?? digest({ contract: row.contractVersion, model: row.modelVersion }),
          dataChecksum: row.dataChecksum ?? row.rowChecksum,
          provenance: row.provenance ?? { backfilled: true },
          ...(yahoo ? { observationMode: "HISTORICAL_RECONSTRUCTION", liveRecorded: false,
            freshness: row.sourceRetrievedAt.getTime() < Date.now() - FRESHNESS_SLA_MS ? "STALE" : "RESEARCH" } : {}),
        }).where(eq(signalEvents.eventId, row.eventId));
      }
    });
    normalizationComplete = true;
    return;
  }
  const artifact = await loadVerifiedSignals();
  const generated = asDate(artifact.signalManifest["generated_at_utc"]);
  const retrieved = asDate(artifact.latestMetadata["retrieved_at_utc"]);
  const model = String(artifact.signalManifest["model_version"]);
  const snapshot = String(artifact.signalManifest["signal_snapshot_id"]);
  const inputSnapshot = String(artifact.signalManifest["input_data_snapshot_id"]);
  const publishedMetadata = {
    signalManifest: artifact.signalManifest,
    dataManifest: artifact.dataManifest,
    coverage: artifact.coverage,
    latest: artifact.latestMetadata,
    historySha256: artifact.signalManifest["signal_history_sha256"],
    bounds: { first: artifact.history[0]?.date, last: artifact.history.at(-1)?.date },
    rowCount: artifact.history.length,
  };
  const runId = digest({ contract: CONTRACT_VERSION, snapshot, generated: generated.toISOString() });
  const rows = artifact.history.map((signal) => {
    const market = marketClose(signal.date);
      const available = new Date(Math.max(
        market.getTime() + 6 * 3600_000,
        retrieved.getTime(),
        generated.getTime(),
      ));
    const rowChecksum = digest(signal);
    const eventId = deterministicEventId({
      modelVersion: model,
      sessionDate: signal.date,
      inputSnapshotId: inputSnapshot,
    });
    return {
      eventId, sessionDate: signal.date, availableAt: available, marketAsOf: market,
      computedAt: generated, sourceRetrievedAt: retrieved,
      observationMode: "HISTORICAL_RECONSTRUCTION", liveRecorded: false,
      contractVersion: CONTRACT_VERSION, modelVersion: model, inputSnapshotId: inputSnapshot,
      signalSnapshotId: snapshot,
      inputChecksum: digest({ snapshot: inputSnapshot, source: artifact.signalManifest["input_source"] }),
      rowChecksum, signal,
      revisionId: snapshot,
      observationAt: retrieved,
      sourceMode: "HISTORICAL_RECONSTRUCTION",
      validFrom: available,
      validUntil: new Date(Math.max(
        market.getTime() + 6 * 3_600_000,
        generated.getTime(),
        retrieved.getTime(),
      ) + 72 * 3_600_000),
      ingestedAt: new Date(),
      freshness: "RESEARCH",
      quality: "VERIFIED",
      providerLineage: { provider: "yahoo", source: SOURCE, mode: "HISTORICAL_RECONSTRUCTION" },
      configChecksum: digest({ contract: CONTRACT_VERSION, model }),
      dataChecksum: rowChecksum,
      provenance: { source: "verified-artifact", reconstructed: true },
    };
  });
  await db.transaction(async (tx) => {
    const [{ count: current }] = await tx.select({ count: sql<number>`count(*)` }).from(signalEvents);
    if (Number(current) !== 0) return;
    const started = new Date();
    await tx.insert(signalIngestionRuns).values({
      runId, logicalKey: `backfill:${snapshot}`, trigger: "BACKFILL",
      attempt: 1, watermark: artifact.history.at(-1)?.date,
      startedAt: started, completedAt: new Date(), status: "SUCCEEDED",
      rowCount: rows.length, sourceMetadata: publishedMetadata,
    });
    for (let i = 0; i < rows.length; i += 500) {
      await tx.insert(signalEvents).values(rows.slice(i, i + 500)).onConflictDoUpdate({
        target: signalEvents.eventId,
        set: {
          availableAt: sql`excluded.available_at`, marketAsOf: sql`excluded.market_as_of`,
          computedAt: sql`excluded.computed_at`, sourceRetrievedAt: sql`excluded.source_retrieved_at`,
          signal: sql`excluded.signal`, rowChecksum: sql`excluded.row_checksum`,
           signalSnapshotId: sql`excluded.signal_snapshot_id`,
        },
      });
    }
    await tx.insert(signalSourceState).values({
      source: SOURCE, status: "HEALTHY", lastGoodAt: new Date(),
      lastAttemptAt: new Date(), lastRetrievedAt: retrieved,
      watermark: artifact.history.at(-1)?.date,
      inputSnapshotId: inputSnapshot, signalSnapshotId: snapshot,
      metadata: publishedMetadata,
    }).onConflictDoUpdate({
      target: signalSourceState.source,
      set: {
        status: "HEALTHY", lastGoodAt: new Date(), lastAttemptAt: new Date(),
        lastRetrievedAt: retrieved, watermark: artifact.history.at(-1)?.date,
        inputSnapshotId: inputSnapshot, signalSnapshotId: snapshot,
        metadata: publishedMetadata, error: null,
      },
    });
  });
}

export type HistoryOptions = {
  start?: string; end?: string; modelVersion?: string; asOf?: Date;
  limit: number; cursor?: string;
};

function decodeCursor(cursor?: string): { sessionDate: string; eventId: string } | undefined {
  if (!cursor) return undefined;
  const [sessionDate, eventId] = Buffer.from(cursor, "base64url").toString().split("|");
  if (!sessionDate || !eventId || !/^\d{4}-\d{2}-\d{2}$/.test(sessionDate)) {
    throw new Error("Invalid cursor.");
  }
  return { sessionDate, eventId };
}
export function encodeCursor(row: { sessionDate: string; eventId: string }): string {
  return Buffer.from(`${row.sessionDate}|${row.eventId}`).toString("base64url");
}

export async function querySignals(options: HistoryOptions) {
  await seedIfEmpty();
  const asOf = options.asOf ?? new Date();
  const filters = [lte(signalEvents.availableAt, asOf), lte(signalEvents.computedAt, asOf)];
  if (options.start) filters.push(sql`${signalEvents.sessionDate} >= ${options.start}`);
  if (options.end) filters.push(sql`${signalEvents.sessionDate} <= ${options.end}`);
  if (options.modelVersion) filters.push(eq(signalEvents.modelVersion, options.modelVersion));
  const cursor = decodeCursor(options.cursor);
  if (cursor) {
    filters.push(gt(
      sql`(${signalEvents.sessionDate}, ${signalEvents.eventId})`,
      sql`(${cursor.sessionDate}, ${cursor.eventId})`,
    ));
  }
  const countFilters = [...filters];
  const base = db.select().from(signalEvents).where(and(...filters));
  const rows = await base.orderBy(asc(signalEvents.sessionDate), asc(signalEvents.eventId)).limit(options.limit + 1);
  if (cursor) countFilters.pop();
  const [{ total }] = await db.select({ total: sql<number>`count(*)` }).from(signalEvents).where(and(...countFilters));
  return { rows: rows.slice(0, options.limit), total: Number(total), nextCursor: rows.length > options.limit ? encodeCursor(rows[options.limit - 1]) : undefined };
}

export async function latestSignal() {
  await seedIfEmpty();
  const now = new Date();
  const [row] = await db.select().from(signalEvents)
    .where(and(
      lte(signalEvents.availableAt, now),
      eq(signalEvents.observationMode, "LIVE_REGISTERED"),
      eq(signalEvents.liveRecorded, true),
      eq(signalEvents.freshness, "FRESH"),
      sql`${signalEvents.validUntil} is not null and ${signalEvents.validUntil} > ${now}`,
      sql`${signalEvents.validFrom} is not null and ${signalEvents.validFrom} <= ${now}`,
      sql`${signalEvents.computedAt} <= ${now} and ${signalEvents.observationAt} is not null and ${signalEvents.observationAt} <= ${now}`,
      sql`${signalEvents.providerLineage} is not null and coalesce(${signalEvents.providerLineage}->>'provider', '') not in ('', 'yahoo', 'yahoo_daily')`,
      sql`${signalEvents.sourceRetrievedAt} >= ${new Date(now.getTime() - FRESHNESS_SLA_MS)}`,
    ))
    .orderBy(desc(signalEvents.availableAt), desc(signalEvents.eventId)).limit(1);
  return row;
}

/** Operational read: only a fresh, non-expired live registration is eligible. */
export async function operationalLatestSignal() {
  return latestSignal();
}

export async function sourceProvenance() {
  await seedIfEmpty();
  const [state] = await db.select().from(signalSourceState).where(eq(signalSourceState.source, SOURCE)).limit(1);
  const [run] = await db.select().from(signalIngestionRuns).orderBy(desc(signalIngestionRuns.startedAt)).limit(1);
  const metadata = state?.metadata as Record<string, unknown> | undefined;
  const artifact = metadata?.coverage ? undefined : await loadVerifiedSignals();
  const sameSnapshot = Boolean(artifact &&
    state?.signalSnapshotId === artifact.signalManifest["signal_snapshot_id"]);
  return {
    state,
    run,
    // DB metadata is authoritative for what was actually published.
    manifest: (metadata?.signalManifest as Record<string, unknown> | undefined) ??
      (sameSnapshot ? artifact?.signalManifest : undefined),
    dataManifest: metadata?.dataManifest ?? (sameSnapshot ? artifact?.dataManifest : undefined),
    coverage: metadata?.coverage ?? (sameSnapshot ? artifact?.coverage : undefined),
    latest: metadata?.latest ?? (sameSnapshot ? artifact?.latestMetadata : undefined),
  };
}

export async function signalBounds() {
  await seedIfEmpty();
  const [{ count }] = await db.select({ count: sql<number>`count(*)` }).from(signalEvents);
  const [first] = await db.select({ date: signalEvents.sessionDate }).from(signalEvents)
    .orderBy(asc(signalEvents.sessionDate)).limit(1);
  const [last] = await db.select({ date: signalEvents.sessionDate }).from(signalEvents)
    .orderBy(desc(signalEvents.sessionDate)).limit(1);
  return { count: Number(count), first: first?.date, last: last?.date };
}

function schedulerStateFromRow(
  state: typeof signalSourceState.$inferSelect | undefined,
): SourceState {
  return {
    watermark: state?.watermark ?? "",
    inputSnapshotId: state?.inputSnapshotId ?? "",
    fresh: state?.status === "HEALTHY",
    checkedAt: state?.lastAttemptAt ?? new Date(0),
  };
}

async function withSchedulerLock<T>(
  lockKey: bigint,
  work: () => Promise<T>,
): Promise<T | null> {
  const client = await pool.connect();
  try {
    const locked = await client.query<{ locked: boolean }>(
      "select pg_try_advisory_lock($1) as locked",
      [lockKey.toString()],
    );
    if (!locked.rows[0]?.locked) return null;
    try {
      return await work();
    } finally {
      await client.query("select pg_advisory_unlock($1)", [lockKey.toString()]);
    }
  } finally {
    client.release();
  }
}

async function beginSchedulerRun(input: {
  logicalKey: string;
  watermark: string;
  inputSnapshotId: string;
  attempt: number;
}): Promise<IngestionRun> {
  const startedAt = new Date();
  // Recover abandoned leases after a process/node disappears. The advisory
  // lock protects this transition from another scheduler tick.
  await db.update(signalIngestionRuns).set({
    status: "FAILED",
    completedAt: startedAt,
    error: "Lease expired; recovered by a later scheduler run.",
    leaseUntil: null,
  }).where(and(
    eq(signalIngestionRuns.status, "RUNNING"),
    or(isNull(signalIngestionRuns.leaseUntil), lt(signalIngestionRuns.leaseUntil, startedAt)),
  ));
  const runId = digest({
    logicalKey: input.logicalKey,
    attempt: input.attempt,
    startedAt: startedAt.toISOString(),
  });
  await db.insert(signalIngestionRuns).values({
    runId,
    logicalKey: input.logicalKey,
    trigger: "SCHEDULED",
    attempt: input.attempt,
    watermark: input.watermark || null,
    startedAt,
    status: "RUNNING",
    rowCount: 0,
    sourceMetadata: { input_snapshot_id: input.inputSnapshotId },
    leaseUntil: new Date(startedAt.getTime() + 15 * 60_000),
    heartbeatAt: startedAt,
  });
  await db.insert(signalSourceState).values({
    source: SOURCE,
    status: "RUNNING",
    watermark: input.watermark || null,
    inputSnapshotId: input.inputSnapshotId || null,
    lastAttemptAt: startedAt,
    metadata: {},
  }).onConflictDoUpdate({
    target: signalSourceState.source,
    set: { status: "RUNNING", lastAttemptAt: startedAt, error: null },
  });
  return {
    id: runId,
    logicalKey: input.logicalKey,
    attempt: input.attempt,
    status: "RUNNING",
  };
}

async function finishSchedulerRun(
  runId: string,
  result: { status: "SUCCEEDED" | "FAILED"; error?: string; rowCount?: number },
): Promise<void> {
  await db.update(signalIngestionRuns)
    .set({
      status: result.status,
      completedAt: new Date(),
      error: result.error ?? null,
      rowCount: result.rowCount ?? 0,
      leaseUntil: null,
      heartbeatAt: new Date(),
    })
    .where(and(
      eq(signalIngestionRuns.runId, runId),
      eq(signalIngestionRuns.status, "RUNNING"),
    ));
  if (result.status === "FAILED") {
    await db.update(signalSourceState)
       .set({ status: "ERROR", error: result.error ?? "Signal refresh failed." })
      .where(eq(signalSourceState.source, SOURCE));
  }
}

async function publishStagedSignals(
  stagingDirectory: string,
  input: { logicalKey?: string; watermark?: string; runId?: string } = {},
): Promise<{ published: boolean; watermark: string; insertedCount: number }> {
  const staged = await loadVerifiedSignalsFrom(stagingDirectory);
  const generated = asDate(staged.signalManifest["generated_at_utc"]);
  const retrieved = asDate(staged.latestMetadata["retrieved_at_utc"]);
  const model = String(staged.signalManifest["model_version"]);
  const inputSnapshot = String(staged.signalManifest["input_data_snapshot_id"]);
  const signalSnapshot = String(staged.signalManifest["signal_snapshot_id"]);
  const [current] = await db.select({ date: signalEvents.sessionDate })
    .from(signalEvents)
    .orderBy(desc(signalEvents.sessionDate))
    .limit(1);
  const previousWatermark = current?.date ?? "";
  const newSignals = staged.history.filter((signal) => signal.date > previousWatermark);
  const inputChecksum = digest({
    snapshot: inputSnapshot,
    source: staged.signalManifest["input_source"],
  });
  const rows = newSignals.map((signal) => {
    const market = marketClose(signal.date);
    // Yahoo is a research/reconstruction source, never a registered live
    // provider. Keep this explicit even when retrieval is near real time.
    const liveRecorded = false;
    return {
      eventId: deterministicEventId({
        modelVersion: model,
        sessionDate: signal.date,
        inputSnapshotId: inputSnapshot,
      }),
      sessionDate: signal.date,
      marketAsOf: market,
      availableAt: new Date(Math.max(
        market.getTime() + 6 * 3_600_000,
        generated.getTime(),
        retrieved.getTime(),
      )),
      computedAt: generated,
      sourceRetrievedAt: retrieved,
      observationMode: liveRecorded
        ? "LIVE_REGISTERED"
        : "HISTORICAL_RECONSTRUCTION",
      sourceMode: liveRecorded ? "LIVE_REGISTERED" : "HISTORICAL_RECONSTRUCTION",
      liveRecorded,
      contractVersion: CONTRACT_VERSION,
      modelVersion: model,
      inputSnapshotId: inputSnapshot,
      signalSnapshotId: signalSnapshot,
      inputChecksum,
      rowChecksum: digest(signal),
      signal,
      revisionId: signalSnapshot,
      observationAt: retrieved,
      validFrom: new Date(Math.max(
        market.getTime() + 6 * 3_600_000,
        generated.getTime(),
        retrieved.getTime(),
      )),
      validUntil: new Date(Math.max(
        market.getTime() + 6 * 3_600_000,
        generated.getTime(),
        retrieved.getTime(),
      ) + 72 * 3600_000),
      ingestedAt: new Date(),
      freshness: "RESEARCH",
      quality: "VERIFIED",
      providerLineage: {
        provider: "yahoo",
        source: SOURCE,
        mode: liveRecorded ? "LIVE_REGISTERED" : "HISTORICAL_RECONSTRUCTION",
      },
      configChecksum: digest({ contract: CONTRACT_VERSION, model }),
      dataChecksum: digest(signal),
      provenance: {
        manifest: staged.signalManifest,
        researchOnly: !liveRecorded,
      },
    };
  });
  const watermark = staged.history.at(-1)?.date ?? previousWatermark;
  const publishedMetadata = {
    signalManifest: staged.signalManifest,
    dataManifest: staged.dataManifest,
    coverage: staged.coverage,
    latest: staged.latestMetadata,
    historySha256: staged.signalManifest["signal_history_sha256"],
    bounds: { first: staged.history[0]?.date, last: staged.history.at(-1)?.date },
    rowCount: staged.history.length,
  };
  await db.transaction(async (tx) => {
    if (rows.length > 0) {
      await tx.insert(signalEvents).values(rows).onConflictDoNothing();
      await tx.insert(signalSourceState).values({
      source: SOURCE,
      status: "HEALTHY",
      watermark,
      inputSnapshotId: inputSnapshot,
      signalSnapshotId: signalSnapshot,
      lastAttemptAt: new Date(),
      lastGoodAt: new Date(),
      lastRetrievedAt: retrieved,
       metadata: publishedMetadata,
    }).onConflictDoUpdate({
      target: signalSourceState.source,
      set: {
        status: "HEALTHY",
        watermark,
        inputSnapshotId: inputSnapshot,
        signalSnapshotId: signalSnapshot,
        lastAttemptAt: new Date(),
        lastGoodAt: new Date(),
        lastRetrievedAt: retrieved,
         metadata: publishedMetadata,
        error: null,
       },
      });
    } else {
      // A no-op refresh must release RUNNING without advancing the last-good
      // snapshot, watermark, or provenance.
      await tx.update(signalSourceState).set({
        status: "HEALTHY",
        lastAttemptAt: new Date(),
        error: null,
      }).where(eq(signalSourceState.source, SOURCE));
    }
    if (input.runId) {
      await tx.update(signalIngestionRuns).set({
        status: "SUCCEEDED",
        completedAt: new Date(),
        rowCount: rows.length,
        leaseUntil: null,
        heartbeatAt: new Date(),
        sourceMetadata: publishedMetadata,
      }).where(eq(signalIngestionRuns.runId, input.runId));
    }
  });
  return {
    published: rows.length > 0,
    watermark,
    insertedCount: rows.length,
  };
}

export const signalSchedulerRepository: SignalSchedulerRepository = {
  withAdvisoryLock: withSchedulerLock,
  async getSourceState() {
    await seedIfEmpty();
    const [state] = await db.select().from(signalSourceState)
      .where(eq(signalSourceState.source, SOURCE))
      .limit(1);
    return schedulerStateFromRow(state);
  },
  beginIngestionRun: beginSchedulerRun,
  finishIngestionRun: finishSchedulerRun,
  publishStagedOutput: publishStagedSignals,
};