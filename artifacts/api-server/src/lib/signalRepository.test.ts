import assert from "node:assert/strict";
import test from "node:test";
import {
  deterministicEventId,
  latestSignal,
  querySignals,
  signalBounds,
} from "./signalRepository.js";

test("idempotent backfill contains the complete historical book", async () => {
  const first = await signalBounds();
  const second = await signalBounds();
  assert.deepEqual(first, second);
  assert.equal(first.count, 4_146);
  assert.equal(first.first, "2010-03-30");
  assert.equal(first.last, "2026-09-18");
});

test("every public event has deterministic PIT lineage", async () => {
  const latest = await latestSignal();
  assert.ok(latest);
  assert.equal(
    latest.eventId,
    deterministicEventId({
      modelVersion: latest.modelVersion,
      sessionDate: latest.sessionDate,
      inputSnapshotId: latest.inputSnapshotId,
    }),
  );
  assert.equal(latest.observationMode, "HISTORICAL_RECONSTRUCTION");
  assert.equal(latest.liveRecorded, false);
  for (const value of [
    latest.marketAsOf,
    latest.availableAt,
    latest.computedAt,
    latest.sourceRetrievedAt,
  ]) {
    assert.ok(value instanceof Date);
    assert.equal(Number.isNaN(value.getTime()), false);
  }
  assert.ok(latest.signalSnapshotId);
  assert.ok(latest.rowChecksum);
});

test("as-of excludes events before conservative reconstruction availability", async () => {
  const before = await querySignals({
    asOf: new Date("2026-09-18T22:03:54.000Z"),
    limit: 10,
  });
  const atRetrieval = await querySignals({
    asOf: new Date("2026-09-18T22:03:55.000Z"),
    limit: 10,
  });
  const afterPublicationDelay = await querySignals({
    asOf: new Date("2026-09-19T02:00:00.000Z"),
    limit: 10,
  });
  assert.equal(before.total, 0);
  assert.equal(atRetrieval.total, 4_145);
  assert.equal(afterPublicationDelay.total, 4_146);
});

test("history pagination is chronological and stable", async () => {
  const first = await querySignals({ limit: 2 });
  assert.equal(first.rows[0]?.sessionDate, "2010-03-30");
  assert.equal(first.rows[1]?.sessionDate, "2010-03-31");
  assert.ok(first.nextCursor);
  const second = await querySignals({ limit: 2, cursor: first.nextCursor });
  assert.equal(second.rows[0]?.sessionDate, "2010-04-01");
  assert.equal(second.total, 4_146);
});