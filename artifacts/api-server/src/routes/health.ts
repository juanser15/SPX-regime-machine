import { Router, type IRouter } from "express";
import { HealthCheckResponse } from "@workspace/api-zod";
import { getSignalArtifactDiagnostic } from "../lib/signalStore";

const router: IRouter = Router();

router.get("/healthz", async (_req, res) => {
  const signalArtifacts = await getSignalArtifactDiagnostic();
  const data = HealthCheckResponse.parse({
    status: signalArtifacts.status === "ready" ? "ok" : "degraded",
    signal_artifacts: signalArtifacts,
  });
  res.status(signalArtifacts.status === "ready" ? 200 : 503).json(data);
});

export default router;
