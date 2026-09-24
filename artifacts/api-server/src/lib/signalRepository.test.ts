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
  // Yahoo is research-only and must never be exposed as an operational live
  // signal, even when the reconstructed book has a current session.
  assert.equal(latest, undefined);
  const history = await querySignals({ limit: 4_146 });
  assert.equal(history.rows.length, 4_146);
  for (const row of history.rows) {
    assert.equal(row.liveRecorded, false);
    assert.ok(row.validUntil instanceof Date);
    assert.ok(row.validFrom instanceof Date);
    assert.ok(row.validUntil.getTime() > row.validFrom.getTime());
    assert.ok(row.revisionId);
    assert.ok(row.configChecksum);
    assert.ok(row.dataChecksum);
  }
  const last = history.rows.at(-1);
  assert.ok(last);
  assert.equal(
    last.eventId,
    deterministicEventId({
      modelVersion: last.modelVersion,
      sessionDate: last.sessionDate,
      inputSnapshotId: last.inputSnapshotId,
    }),
  );
  assert.equal(last.observationMode, "HISTORICAL_RECONSTRUCTION");
  assert.equal(last.sourceMode, "HISTORICAL_RECONSTRUCTION");
  assert.equal(last.liveRecorded, false);
  assert.ok(last.validUntil instanceof Date);
  assert.ok(last.validFrom instanceof Date);
  assert.ok(last.observationAt instanceof Date);
  assert.equal(last.freshness === "RESEARCH" || last.freshness === "STALE", true);
  assert.ok(last.providerLineage);
  assert.ok(last.dataChecksum);
  assert.ok(last.provenance);
});

test("as-of excludes before computedAt and includes exact computedAt boundary", async () => {
  const all = await querySignals({ limit: 4_146 });
  const computedAt = all.rows[0]?.computedAt;
  assert.ok(computedAt instanceof Date);
  const before = await querySignals({
    asOf: new Date(computedAt.getTime() - 1),
    limit: 4_146,
  });
  const atComputed = await querySignals({ asOf: computedAt, limit: 4_146 });
  assert.equal(before.total, 0);
  // Some rows remain unavailable until the conservative market-close delay,
  // but rows whose availableAt is exactly computedAt are included.
  assert.ok(atComputed.total > 0);
  assert.ok(atComputed.total < 4_146);
  assert.ok(atComputed.rows.every((row) =>
    row.availableAt.getTime() <= computedAt.getTime() &&
    row.computedAt.getTime() <= computedAt.getTime()));
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