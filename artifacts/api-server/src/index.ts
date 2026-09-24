import app from "./app";
import { logger } from "./lib/logger";
import { getSignalArtifactDiagnostic } from "./lib/signalStore";
import { latestSignal } from "./lib/signalRepository";

const rawPort = process.env["PORT"];

if (!rawPort) {
  throw new Error(
    "PORT environment variable is required but was not provided.",
  );
}

const port = Number(rawPort);

if (Number.isNaN(port) || port <= 0) {
  throw new Error(`Invalid PORT value: "${rawPort}"`);
}

const signalArtifacts = await getSignalArtifactDiagnostic();
if (signalArtifacts.status === "ready") {
  logger.info({ signalArtifacts }, "Verified signal artifacts ready");
} else {
  logger.error({ signalArtifacts }, "Verified signal artifacts unavailable");
}

try {
  const latest = await latestSignal();
  logger.info(
    { eventId: latest?.eventId, sessionDate: latest?.sessionDate },
    "PostgreSQL operational signal lookup completed",
  );
} catch (error) {
  logger.error({ err: error }, "PostgreSQL signal book unavailable");
}

// Refreshes are intentionally not driven by an in-process timer: autoscaled
// instances are not durable workers. Invoke runScheduledTick from an external
// cron/worker entry point instead.

app.listen(port, (err) => {
  if (err) {
    logger.error({ err }, "Error listening on port");
    process.exit(1);
  }

  logger.info({ port }, "Server listening");
});
