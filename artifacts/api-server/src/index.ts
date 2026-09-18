import app from "./app";
import { logger } from "./lib/logger";
import { getSignalArtifactDiagnostic } from "./lib/signalStore";

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

app.listen(port, (err) => {
  if (err) {
    logger.error({ err }, "Error listening on port");
    process.exit(1);
  }

  logger.info({ port }, "Server listening");
});
