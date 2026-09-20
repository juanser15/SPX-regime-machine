import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const moduleDirectory = dirname(fileURLToPath(import.meta.url));
const workspaceDirectory = resolve(moduleDirectory, "../../..");
const defaultSignalDirectory = resolve(
  workspaceDirectory,
  "spx-flow-machine/data/free_signal",
);

const configuredSignalDirectory = process.env["SIGNAL_DATA_DIR"];
const signalDirectory = configuredSignalDirectory
  ? isAbsolute(configuredSignalDirectory)
    ? configuredSignalDirectory
    : resolve(workspaceDirectory, configuredSignalDirectory)
  : defaultSignalDirectory;

type JsonObject = Record<string, unknown>;

export type SignalObservation = {
  date: string;
  data_lane: string;
  regime: string;
  risk_signal: "RISK-ON" | "NEUTRAL" | "DE-RISK";
  overall_stress_score: number;
  body_stress_score: number;
  tail_risk_hazard_score: number | null;
  confidence_score: number;
  confidence: "LOW" | "MEDIUM" | "HIGH";
  data_quality: string;
  available_component_count: number;
  missing_inputs: string;
  primary_drivers: string;
  score_type: string;
  probability_status: "NOT_CALIBRATED";
};

function parseCsv(content: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < content.length; index += 1) {
    const character = content[index];
    if (quoted) {
      if (character === '"' && content[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
    } else if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (character !== "\r") {
      field += character;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

function requiredString(row: JsonObject, key: string): string {
  const value = row[key];
  if (typeof value !== "string") {
    throw new Error(`Persisted signal field "${key}" is not a string.`);
  }
  return value;
}

function requiredNumber(row: JsonObject, key: string): number {
  const value = Number(row[key]);
  if (!Number.isFinite(value)) {
    throw new Error(`Persisted signal field "${key}" is not numeric.`);
  }
  return value;
}

function toObservation(row: JsonObject): SignalObservation {
  const riskSignal = requiredString(row, "risk_signal");
  const confidence = requiredString(row, "confidence");
  const probabilityStatus = requiredString(row, "probability_status");
  if (!["RISK-ON", "NEUTRAL", "DE-RISK"].includes(riskSignal)) {
    throw new Error(`Unexpected persisted risk signal "${riskSignal}".`);
  }
  if (!["LOW", "MEDIUM", "HIGH"].includes(confidence)) {
    throw new Error(`Unexpected persisted confidence "${confidence}".`);
  }
  if (probabilityStatus !== "NOT_CALIBRATED") {
    throw new Error("Persisted signals must retain NOT_CALIBRATED semantics.");
  }

  const tailRaw = row["tail_risk_hazard_score"];
  const tail =
    tailRaw === null || tailRaw === undefined || tailRaw === ""
      ? null
      : requiredNumber(row, "tail_risk_hazard_score");

  return {
    date: requiredString(row, "date").slice(0, 10),
    data_lane: requiredString(row, "data_lane"),
    regime: requiredString(row, "regime"),
    risk_signal: riskSignal as SignalObservation["risk_signal"],
    overall_stress_score: requiredNumber(row, "overall_stress_score"),
    body_stress_score: requiredNumber(row, "body_stress_score"),
    tail_risk_hazard_score: tail,
    confidence_score: requiredNumber(row, "confidence_score"),
    confidence: confidence as SignalObservation["confidence"],
    data_quality: requiredString(row, "data_quality"),
    available_component_count: requiredNumber(
      row,
      "available_component_count",
    ),
    missing_inputs: requiredString(row, "missing_inputs"),
    primary_drivers: requiredString(row, "primary_drivers"),
    score_type: requiredString(row, "score_type"),
    probability_status: "NOT_CALIBRATED",
  };
}

function observationsMatch(
  latest: SignalObservation,
  historical: SignalObservation,
): boolean {
  const numericKeys = [
    "overall_stress_score",
    "body_stress_score",
    "tail_risk_hazard_score",
    "confidence_score",
  ] as const;
  const textKeys = [
    "date",
    "data_lane",
    "regime",
    "risk_signal",
    "confidence",
    "data_quality",
    "missing_inputs",
    "probability_status",
  ] as const;
  const textMatches = textKeys.every(
    (key) => latest[key] === historical[key],
  );
  const numericMatches = numericKeys.every((key) => {
    const left = latest[key];
    const right = historical[key];
    if (left === null || right === null) {
      return left === right;
    }
    return Math.abs(left - right) <= 1e-7;
  });
  return textMatches && numericMatches;
}

async function readJson(directory: string, fileName: string): Promise<JsonObject> {
  return JSON.parse(
    await readFile(resolve(directory, fileName), "utf8"),
  ) as JsonObject;
}

export async function loadVerifiedSignalsFrom(directory: string): Promise<{
  latest: SignalObservation;
  latestMetadata: JsonObject;
  history: SignalObservation[];
  signalManifest: JsonObject;
  dataManifest: JsonObject;
  coverage: JsonObject;
}> {
  const historyPayload = await readFile(
    resolve(directory, "signal_history.csv"),
    "utf8",
  );
  const signalManifest = await readJson(directory, "signal_manifest.json");
  const expectedHash = requiredString(
    signalManifest,
    "signal_history_sha256",
  );
  const actualHash = createHash("sha256").update(historyPayload).digest("hex");
  if (actualHash !== expectedHash) {
    throw new Error("Persisted signal history checksum mismatch.");
  }

  const [headers, ...records] = parseCsv(historyPayload);
  if (!headers || records.length === 0) {
    throw new Error("Persisted signal history is empty.");
  }
  const history = records.map((values) =>
    toObservation(
      Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])),
    ),
  );

  const latestMetadata = await readJson(directory, "latest_signal.json");
  const latest = toObservation(latestMetadata);
  const lastHistorical = history.at(-1);
  if (!lastHistorical || !observationsMatch(latest, lastHistorical)) {
    throw new Error(
      "Persisted latest signal does not match the last historical observation.",
    );
  }

  const [dataManifest, coverage] = await Promise.all([
    readJson(directory, "daily_data/metadata_manifest.json"),
    readJson(directory, "daily_data/coverage_report.json"),
  ]);
  return {
    latest,
    latestMetadata,
    history,
    signalManifest,
    dataManifest,
    coverage,
  };
}

export async function loadVerifiedSignals() {
  return loadVerifiedSignalsFrom(signalDirectory);
}

export type SignalArtifactDiagnostic =
  | {
      status: "ready";
      model_version: string;
      history_row_count: number;
      history_first_date: string;
      history_last_date: string;
    }
  | {
      status: "unavailable";
      reason: "missing_or_invalid";
    };

export async function getSignalArtifactDiagnostic(): Promise<SignalArtifactDiagnostic> {
  try {
    const store = await loadVerifiedSignals();
    return {
      status: "ready",
      model_version: String(store.signalManifest["model_version"]),
      history_row_count: store.history.length,
      history_first_date: store.history[0]?.date ?? "",
      history_last_date: store.history.at(-1)?.date ?? "",
    };
  } catch {
    return {
      status: "unavailable",
      reason: "missing_or_invalid",
    };
  }
}