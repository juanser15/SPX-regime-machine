import { logger } from "./lib/logger";
import { signalSchedulerRepository } from "./lib/signalRepository";
import { runScheduledTick } from "./lib/signalScheduler";

// Invoke this process from an independently scheduled job. The HTTP API is
// autoscaled and cannot provide a reliable clock for post-close work.
try {
  const result = await runScheduledTick(signalSchedulerRepository);
  logger.info({ result }, "Scheduled signal tick finished");
  if (result.status === "ERROR") process.exitCode = 1;
} catch (error) {
  logger.error({ err: error }, "Scheduled signal tick failed");
  process.exitCode = 1;
}