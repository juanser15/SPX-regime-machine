import { Router, type IRouter } from "express";
import { desc, eq, sql } from "drizzle-orm";
import { db } from "@workspace/db";
import { signalEvents, signalIngestionRuns, signalSourceState } from "@workspace/db/schema";
import { getSignalArtifactDiagnostic } from "../lib/signalStore";
import { nextWeekdayPostClose } from "../lib/signalScheduler";
import { operationalLatestSignal } from "../lib/signalRepository";
import { HealthCheckResponse } from "@workspace/api-zod";

const router: IRouter = Router();
const SLA_HOURS = 72;
const iso = (value: Date | null | undefined) => value?.toISOString() ?? null;

router.get("/healthz", async (req, res) => {
  res.set("Cache-Control", "private, no-store");
  let artifact: Awaited<ReturnType<typeof getSignalArtifactDiagnostic>> | undefined;
  try {
    artifact = await getSignalArtifactDiagnostic();
    const [{ count }] = await db.select({ count: sql<number>`count(*)` }).from(signalEvents);
    const [state] = await db.select().from(signalSourceState)
      .where(eq(signalSourceState.source, "yahoo_daily")).limit(1);
    const [lastRun] = await db.select().from(signalIngestionRuns)
      .where(eq(signalIngestionRuns.trigger, "SCHEDULED"))
      .orderBy(desc(signalIngestionRuns.startedAt)).limit(1);
    const [lastScheduledSuccess] = await db.select().from(signalIngestionRuns)
      .where(sql`${signalIngestionRuns.trigger} = 'SCHEDULED' and ${signalIngestionRuns.status} = 'SUCCEEDED'`)
      .orderBy(desc(signalIngestionRuns.completedAt)).limit(1);
    const now = new Date();
    const ageHours = state?.lastRetrievedAt
      ? Math.max(0, (now.getTime() - state.lastRetrievedAt.getTime()) / 3_600_000) : null;
    const sourceFresh = ageHours !== null && ageHours <= SLA_HOURS && state?.status !== "ERROR";
    const persistence = Number(count) > 0;
    const integrity = artifact.status === "ready";
    const computation = Boolean(lastScheduledSuccess);
    const live = await operationalLatestSignal().catch(() => undefined);
    const eligible = Boolean(live);
    // A stale/research-only producer remains available for historical reads.
    // Reserve HTTP 503 for failure to serve the stored history itself.
    const status = !integrity || !persistence ? "ERROR" :
      eligible && sourceFresh && computation ? "HEALTHY" : "STALE";
    const body = {
      status,
      freshness_sla_hours: SLA_HOURS,
      integrity: { status: integrity ? "HEALTHY" : "ERROR", artifact },
      connectivity: { status: "HEALTHY", database: "reachable" },
      source_freshness: {
        status: sourceFresh ? "FRESH" : (state?.status === "ERROR" ? "ERROR" : "STALE"),
        age_hours: ageHours, last_retrieved_at: iso(state?.lastRetrievedAt),
        last_scheduled_success: iso(lastScheduledSuccess?.completedAt),
        next_weekday_expected_session: nextWeekdayPostClose(now).toISOString(),
        blocker: sourceFresh ? null : (state?.error ?? "Source data is older than the 72-hour freshness SLA."),
      },
      computation: {
        status: computation ? "HEALTHY" : "ERROR",
        last_scheduled_success: iso(lastScheduledSuccess?.completedAt),
        blocker: computation ? null : (lastRun?.error ?? "No successful scheduled computation exists."),
      },
      persistence: { status: persistence ? "HEALTHY" : "ERROR", signal_event_count: Number(count),
        blocker: persistence ? null : "No persisted signal events exist." },
      hub_eligibility: {
        status: eligible ? "READY" : (sourceFresh ? "STALE" : "ERROR"),
        last_live_eligible_event: live ? { event_id: live.eventId, session_date: live.sessionDate, available_at: live.availableAt.toISOString() } : null,
        next_expected_session: nextWeekdayPostClose(now).toISOString(),
        blocker: eligible ? null : "No eligible live signal is available; research history is not operational.",
      },
    };
    res.status(status === "ERROR" ? 503 : 200).json(HealthCheckResponse.parse(body));
  } catch (error) {
    req.log.error({ err: error }, "Health check database failure");
    res.status(503).json(HealthCheckResponse.parse({
      status: "ERROR", freshness_sla_hours: SLA_HOURS,
      integrity: { status: "ERROR", artifact: artifact ?? { status: "unavailable" } },
      connectivity: { status: "ERROR", database: "unreachable", blocker: "Database unavailable." },
      source_freshness: { status: "ERROR", blocker: "Database unavailable." },
      computation: { status: "ERROR", blocker: "Database unavailable." },
      persistence: { status: "ERROR", blocker: "Database unavailable." },
      hub_eligibility: { status: "ERROR", blocker: "Database unavailable." },
    }));
  }
});
export default router;