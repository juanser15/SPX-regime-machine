import app from "./app";
import { logger } from "./lib/logger";
import { getSignalArtifactDiagnostic } from "./lib/signalStore";
import { latestSignal, signalSchedulerRepository } from "./lib/signalRepository";
import {
  isWeekdayPostCloseEligible,
  nextWeekdayPostClose,
  runWeekdayPostClose,
} from "./lib/signalScheduler";

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
    "PostgreSQL signal book ready",
  );
} catch (error) {
  logger.error({ err: error }, "PostgreSQL signal book unavailable");
}

const maximumTimerDelay = 2_147_000_000;
function scheduleSignalRefresh(): void {
  const now = new Date();
  const next = nextWeekdayPostClose(now);
  const delay = Math.min(
    maximumTimerDelay,
    Math.max(1_000, next.getTime() - now.getTime()),
  );
  setTimeout(async () => {
    try {
      const result = await runWeekdayPostClose(signalSchedulerRepository);
      logger.info({ result }, "Scheduled signal refresh completed");
    } catch (error) {
      logger.error({ err: error }, "Scheduled signal refresh failed");
    } finally {
      scheduleSignalRefresh();
    }
  }, delay);
  logger.info({ nextRunAt: next.toISOString() }, "Signal refresh scheduled");
}

if (isWeekdayPostCloseEligible(new Date())) {
  void runWeekdayPostClose(signalSchedulerRepository)
    .then((result) => logger.info({ result }, "Startup signal refresh completed"))
    .catch((error) => logger.error({ err: error }, "Startup signal refresh failed"));
}
scheduleSignalRefresh();

app.listen(port, (err) => {
  if (err) {
    logger.error({ err }, "Error listening on port");
    process.exit(1);
  }

  logger.info({ port }, "Server listening");
});
