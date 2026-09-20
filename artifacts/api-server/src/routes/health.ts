import { Router, type IRouter } from "express";
import { sql } from "drizzle-orm";
import { db } from "@workspace/db";
import { signalEvents, signalSourceState } from "@workspace/db/schema";
import { getSignalArtifactDiagnostic } from "../lib/signalStore";

const router: IRouter = Router();

router.get("/healthz", async (req, res) => {
  const artifact = await getSignalArtifactDiagnostic();
  try {
    const [{ count }] = await db.select({ count: sql<number>`count(*)` }).from(signalEvents);
    const [state] = await db.select().from(signalSourceState).limit(1);
    const seeded = Number(count) > 0;
    const freshnessSlaHours = 72;
    const ageHours = state?.lastRetrievedAt
      ? Math.max(0, (Date.now() - state.lastRetrievedAt.getTime()) / 3_600_000)
      : Infinity;
    const freshness = ageHours <= freshnessSlaHours ? "FRESH" : "STALE";
    const status = seeded && artifact.status === "ready"
      ? (state?.status === "ERROR"
        ? "ERROR"
        : freshness === "STALE" || state?.status === "STALE"
          ? "STALE"
          : "HEALTHY")
      : "ERROR";
    const body = {
      status,
      database: { status: "HEALTHY", signal_event_count: Number(count) },
      artifacts: artifact,
      source: state ? { ...state, freshness, freshness_sla_hours: freshnessSlaHours, age_hours: ageHours } : { status: "ERROR", error: seeded ? "Source state unavailable." : "Signal database is unseeded." },
    };
    res.status(status === "ERROR" ? 503 : 200).json(body);
  } catch (error) {
    req.log.error({ err: error }, "Health check database failure");
    res.status(503).json({
      status: "ERROR",
      database: { status: "ERROR" },
      artifacts: artifact,
      source: { status: "ERROR", error: "Database unavailable." },
    });
  }
});

export default router;