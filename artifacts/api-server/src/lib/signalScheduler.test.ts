import assert from "node:assert/strict";
import test from "node:test";
import {
  isEligible,
  nextRunAt,
  runWeekdayPostClose,
  type IngestionRun,
  type SignalSchedulerRepository,
  type SourceState,
} from "./signalScheduler.js";

const fridayAfterClose = new Date("2024-03-09T00:00:00.000Z"); // 19:00 EST
const mondayAfterDst = new Date("2024-03-11T22:00:00.000Z"); // 18:00 EDT

test("next run is a weekday 18:00 New York time across DST", () => {
  assert.equal(nextRunAt(fridayAfterClose).toISOString(), "2024-03-11T22:00:00.000Z");
  assert.equal(nextRunAt(new Date("2024-03-08T22:00:00.000Z")).toISOString(), "2024-03-08T23:00:00.000Z");
  assert.equal(nextRunAt(new Date("2024-03-09T15:00:00.000Z")).toISOString(), "2024-03-11T22:00:00.000Z");
  assert.equal(isEligible(mondayAfterDst), true);
  assert.equal(isEligible(new Date("2024-03-11T21:59:59.000Z")), false);
});

type FakeOptions = { lock?: boolean; command?: string; published?: boolean };
function fakeRepository(options: FakeOptions = {}) {
  const state: SourceState = {
    watermark: "2024-03-08",
    inputSnapshotId: "snapshot-a",
    fresh: true,
    checkedAt: new Date(),
  };
  const runs: IngestionRun[] = [];
  let publishCount = 0;
  const repository: SignalSchedulerRepository = {
    async withAdvisoryLock(_key, work) {
      return options.lock === false ? null : work();
    },
    async getSourceState() { return state; },
    async beginIngestionRun(input) {
      const run = { id: String(runs.length + 1), ...input, status: "RUNNING" as const };
      runs.push(run);
      return run;
    },
    async finishIngestionRun(id, result) {
      const run = runs.find((candidate) => candidate.id === id);
      if (run) run.status = result.status;
    },
    async publishStagedOutput() {
      if (!options.published) publishCount += 1;
      return {
        published: !options.published,
        watermark: state.watermark,
        insertedCount: options.published ? 0 : 1,
      };
    },
  };
  return { repository, runs, get publishCount() { return publishCount; } };
}

test("advisory lock prevents a second concurrent scheduler", async () => {
  const fake = fakeRepository({ lock: false });
  const result = await runWeekdayPostClose(fake.repository, {
    clock: { now: () => mondayAfterDst },
  });
  assert.equal(result.status, "SKIPPED");
  assert.equal(fake.runs.length, 0);
});

test("provider failure is bounded and never publishes staged output", async () => {
  const fake = fakeRepository();
  const result = await runWeekdayPostClose(fake.repository, {
    pythonCommand: "false",
    maxAttempts: 3,
    retryBaseDelayMs: 0,
    retryCapDelayMs: 0,
    clock: { now: () => mondayAfterDst },
  });
  assert.equal(result.status, "ERROR");
  assert.equal(result.attempts, 3);
  assert.equal(fake.runs.length, 3);
  assert.equal(fake.runs.every((run) => run.status === "FAILED"), true);
  assert.equal(fake.publishCount, 0);
});

test("same input snapshot is idempotently skipped after publication", async () => {
  const fake = fakeRepository();
  const first = await runWeekdayPostClose(fake.repository, {
    pythonCommand: "true",
    maxAttempts: 1,
    clock: { now: () => mondayAfterDst },
  });
  assert.equal(first.status, "OK");
  assert.equal(fake.publishCount, 1);

  const second = fakeRepository({ published: true });
  const duplicate = await runWeekdayPostClose(second.repository, {
    pythonCommand: "true",
    maxAttempts: 1,
    clock: { now: () => mondayAfterDst },
  });
  assert.equal(duplicate.status, "SKIPPED");
  assert.equal(second.runs.length, 1);
  assert.equal(second.publishCount, 0);
});