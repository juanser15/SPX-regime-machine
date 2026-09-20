// Export your models here. Add one export per file
// export * from "./posts";
//
// Each model/table should ideally be split into different files.
// Each model/table should define a Drizzle table, insert schema, and types:
//
//   import { pgTable, text, serial } from "drizzle-orm/pg-core";
//   import { createInsertSchema } from "drizzle-zod";
//   import { z } from "zod/v4";
//
//   export const postsTable = pgTable("posts", {
//     id: serial("id").primaryKey(),
//     title: text("title").notNull(),
//   });
//
//   export const insertPostSchema = createInsertSchema(postsTable).omit({ id: true });
//   export type InsertPost = z.infer<typeof insertPostSchema>;
//   export type Post = typeof postsTable.$inferSelect;

import { createInsertSchema } from "drizzle-zod";
import { pgTable, text, timestamp, integer, boolean, jsonb, index } from "drizzle-orm/pg-core";

export const signalEvents = pgTable("signal_events", {
  eventId: text("event_id").primaryKey(),
  sessionDate: text("session_date").notNull(),
  availableAt: timestamp("available_at", { withTimezone: true }).notNull(),
  marketAsOf: timestamp("market_as_of", { withTimezone: true }).notNull(),
  computedAt: timestamp("computed_at", { withTimezone: true }).notNull(),
  sourceRetrievedAt: timestamp("source_retrieved_at", { withTimezone: true }).notNull(),
  observationMode: text("observation_mode").notNull(),
  liveRecorded: boolean("live_recorded").notNull(),
  contractVersion: text("contract_version").notNull(),
  modelVersion: text("model_version").notNull(),
  inputSnapshotId: text("input_snapshot_id").notNull(),
  signalSnapshotId: text("signal_snapshot_id").notNull(),
  inputChecksum: text("input_checksum").notNull(),
  rowChecksum: text("row_checksum").notNull(),
  signal: jsonb("signal").notNull(),
}, (table) => ({
  availableIdx: index("signal_events_available_idx").on(table.availableAt, table.eventId),
  sessionIdx: index("signal_events_session_idx").on(table.sessionDate),
}));

export const signalIngestionRuns = pgTable("signal_ingestion_runs", {
  runId: text("run_id").primaryKey(),
  logicalKey: text("logical_key").notNull(),
  trigger: text("trigger").notNull(),
  attempt: integer("attempt").notNull(),
  watermark: text("watermark"),
  startedAt: timestamp("started_at", { withTimezone: true }).notNull(),
  completedAt: timestamp("completed_at", { withTimezone: true }),
  status: text("status").notNull(),
  rowCount: integer("row_count").notNull(),
  sourceMetadata: jsonb("source_metadata").notNull(),
  error: text("error"),
});

export const signalSourceState = pgTable("signal_source_state", {
  source: text("source").primaryKey(),
  status: text("status").notNull(),
  watermark: text("watermark"),
  inputSnapshotId: text("input_snapshot_id"),
  signalSnapshotId: text("signal_snapshot_id"),
  lastAttemptAt: timestamp("last_attempt_at", { withTimezone: true }),
  lastGoodAt: timestamp("last_good_at", { withTimezone: true }),
  lastRetrievedAt: timestamp("last_retrieved_at", { withTimezone: true }),
  metadata: jsonb("metadata").notNull(),
  error: text("error"),
});

export const insertSignalEventSchema = createInsertSchema(signalEvents);
export const insertSignalIngestionRunSchema = createInsertSchema(signalIngestionRuns);
export const insertSignalSourceStateSchema = createInsertSchema(signalSourceState);
export type SignalEvent = typeof signalEvents.$inferSelect;
export type SignalIngestionRun = typeof signalIngestionRuns.$inferSelect;
export type SignalSourceState = typeof signalSourceState.$inferSelect;
// Explicit table aliases retained for consumers that use the conventional
// `*Table` naming style.
export const signalEventsTable = signalEvents;
export const signalIngestionRunsTable = signalIngestionRuns;
export const signalSourceStateTable = signalSourceState;