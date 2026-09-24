/**
 * Weekday post-close orchestration for the FREE regime signal.
 *
 * This module intentionally contains no persistence implementation.  The
 * repository is supplied by the host so that deployments can use their
 * existing database transaction/connection pool and publication mechanism.
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { mkdtemp, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";

export type SchedulerStatus = "OK" | "ERROR" | "STALE" | "SKIPPED";
export type SourceState = {
  watermark: string;
  inputSnapshotId: string;
  fresh: boolean;
  checkedAt: Date;
};

/** Contract for a future authoritative live provider. Yahoo does not
 * implement this interface and therefore can never produce LIVE_REGISTERED. */
export interface LiveSignalProvider {
  readonly name: string;
  fetchLive(input: { asOf: Date }): Promise<unknown>;
}

export type IngestionRun = {
  id: string;
  logicalKey: string;
  attempt: number;
  status: "RUNNING" | "SUCCEEDED" | "FAILED";
};

export interface SignalSchedulerRepository {
  /** Must use pg_advisory_lock (or an equivalent transaction-scoped lock). */
  withAdvisoryLock<T>(lockKey: bigint, work: () => Promise<T>): Promise<T | null>;
  getSourceState(): Promise<SourceState>;
  beginIngestionRun(input: {
    logicalKey: string;
    watermark: string;
    inputSnapshotId: string;
    attempt: number;
  }): Promise<IngestionRun>;
  finishIngestionRun(
    runId: string,
    result: { status: "SUCCEEDED" | "FAILED"; error?: string; rowCount?: number },
  ): Promise<void>;
  /** Atomically makes staged output visible; never overwrite this on failure. */
  publishStagedOutput(
    stagingDirectory: string,
    input: { logicalKey: string; watermark: string; runId?: string },
  ): Promise<{ published: boolean; watermark: string; insertedCount: number }>;
}

export type SchedulerClock = { now(): Date };
export type RefreshOptions = {
  pythonCommand?: string;
  startDate?: string;
  maxAttempts?: number;
  retryBaseDelayMs?: number;
  retryCapDelayMs?: number;
  clock?: SchedulerClock;
  /** Deliberately absent by default: fail closed rather than inventing live data. */
  liveProvider?: LiveSignalProvider;
};

const ZONE = "America/New_York";
const TARGET_HOUR = 18;
const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_RETRY_BASE_MS = 30_000;
const DEFAULT_RETRY_CAP_MS = 5 * 60_000;
const MODULE_DIRECTORY = dirname(fileURLToPath(import.meta.url));
// The API build bundles this module into dist/index.mjs, while tests/loaders
// may retain src/lib. Probe only paths relative to the module URL (never cwd).
const MODULE_ROOT = [
  resolve(MODULE_DIRECTORY, "../../../.."),
  resolve(MODULE_DIRECTORY, "../../.."),
].find((candidate) => existsSync(resolve(candidate, "spx-flow-machine/src/daily_signal.py"))) ??
  resolve(MODULE_DIRECTORY, "../../../..");
const PYTHON_REFRESH = resolve(MODULE_ROOT, "spx-flow-machine/src/daily_signal.py");

function localParts(date: Date): { year: number; month: number; day: number; hour: number; minute: number; second: number; weekday: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: ZONE, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    weekday: "short",
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  const weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    .indexOf(parts.find((p) => p.type === "weekday")?.value ?? "Sun");
  return { year: get("year"), month: get("month"), day: get("day"), hour: get("hour") % 24, minute: get("minute"), second: get("second"), weekday };
}

/** Convert a New York wall-clock date to an instant, including DST transitions. */
function nyWallClockUtc(year: number, month: number, day: number, hour: number): Date {
  let guess = new Date(Date.UTC(year, month - 1, day, hour));
  for (let i = 0; i < 3; i += 1) {
    const p = localParts(guess);
    const wanted = Date.UTC(year, month - 1, day, hour);
    const actual = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
    guess = new Date(guess.getTime() + (wanted - actual));
  }
  return guess;
}

function addDays(year: number, month: number, day: number, days: number) {
  const d = new Date(Date.UTC(year, month - 1, day + days));
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
}

/** Return the next weekday 18:00 America/New_York instant (never a weekend). */
export function nextWeekdayPostClose(now: Date): Date {
  const p = localParts(now);
  let days = 0;
  if (p.weekday === 0) days = 1;
  else if (p.weekday === 6) days = 2;
  else if (p.hour >= TARGET_HOUR) days = p.weekday === 5 ? 3 : 1;
  const date = addDays(p.year, p.month, p.day, days);
  return nyWallClockUtc(date.year, date.month, date.day, TARGET_HOUR);
}

export function isWeekdayPostCloseEligible(now: Date): boolean {
  const p = localParts(now);
  return p.weekday >= 1 && p.weekday <= 5 && p.hour >= TARGET_HOUR;
}

// Short aliases make these pure policy helpers convenient to use from a
// cron/interval adapter without coupling that adapter to implementation names.
export const nextRunAt = nextWeekdayPostClose;
export const isEligible = isWeekdayPostCloseEligible;

export function retryDelayMs(attempt: number, base = DEFAULT_RETRY_BASE_MS, cap = DEFAULT_RETRY_CAP_MS): number {
  if (!Number.isInteger(attempt) || attempt < 1) throw new RangeError("attempt must be positive");
  return Math.min(cap, base * 2 ** (attempt - 1));
}

/** Stable signed 64-bit PostgreSQL advisory-lock key (two int32 words are avoided). */
export function schedulerLockKey(namespace = "regime-weekday-post-close"): bigint {
  let hash = 2166136261n;
  for (const byte of new TextEncoder().encode(namespace)) hash = BigInt.asIntN(64, (hash ^ BigInt(byte)) * 1099511628211n);
  return hash;
}

export function logicalEventKey(state: Pick<SourceState, "watermark" | "inputSnapshotId">): string {
  return `regime:${state.watermark}:${state.inputSnapshotId}`;
}

function runRefresh(command: string, args: string[]): Promise<void> {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
    let stderr = "";
    child.stderr.on("data", (chunk: Buffer) => { stderr += chunk.toString(); });
    child.once("error", reject);
    child.once("close", (code) => code === 0 ? resolvePromise() : reject(new Error(`refresh exited ${code}: ${stderr.slice(-2_000)}`)));
  });
}

export type SchedulerResult = { status: SchedulerStatus; logicalKey?: string; error?: string; attempts: number };

export async function runWeekdayPostClose(
  repository: SignalSchedulerRepository,
  options: RefreshOptions = {},
): Promise<SchedulerResult> {
  const clock = options.clock ?? { now: () => new Date() };
  const now = clock.now();
  if (!isWeekdayPostCloseEligible(now)) return { status: "SKIPPED", attempts: 0 };
  const result = await repository.withAdvisoryLock<SchedulerResult>(schedulerLockKey(), async (): Promise<SchedulerResult> => {
    const state = await repository.getSourceState();
    const logicalKey = `regime:scheduled:${now.toISOString().slice(0, 10)}`;
    const maxAttempts = options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
    const staging = await mkdtemp(resolve(tmpdir(), "regime-refresh-"));
    try {
      let lastError = "refresh failed";
      for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        const run = await repository.beginIngestionRun({ logicalKey, watermark: state.watermark, inputSnapshotId: state.inputSnapshotId, attempt });
        try {
          const end = new Date(now.getTime() + 86_400_000).toISOString().slice(0, 10);
          // Always refresh into a disposable directory.  Publication is an
          // atomic repository operation, so a failed Python run cannot damage
          // the last-good signal files.
          await runRefresh(options.pythonCommand ?? "python3", [PYTHON_REFRESH, "--start", options.startDate ?? "2010-01-01", "--end", end, "--output-dir", staging]);
           const publication = await repository.publishStagedOutput(staging, { logicalKey, watermark: state.watermark, runId: run.id });
          await repository.finishIngestionRun(run.id, {
            status: "SUCCEEDED",
            rowCount: publication.insertedCount,
          });
          return {
            status: publication.published ? "OK" : "SKIPPED",
            logicalKey,
            attempts: attempt,
          };
        } catch (error) {
          lastError = error instanceof Error ? error.message : String(error);
          await repository.finishIngestionRun(run.id, { status: "FAILED", error: lastError });
          if (attempt < maxAttempts) await new Promise((r) => setTimeout(r, retryDelayMs(attempt, options.retryBaseDelayMs, options.retryCapDelayMs)));
        }
      }
      return { status: "ERROR", logicalKey, attempts: maxAttempts, error: lastError };
    } finally {
      await rm(staging, { recursive: true, force: true });
    }
  });
  return result ?? { status: "SKIPPED", attempts: 0 };
}

/** One-shot entry point for cron/Cloud Scheduler/Kubernetes CronJob. */
export async function runScheduledTick(
  repository: SignalSchedulerRepository,
  options: RefreshOptions = {},
): Promise<SchedulerResult> {
  return runWeekdayPostClose(repository, options);
}