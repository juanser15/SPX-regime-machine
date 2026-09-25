---
name: Persisted audit round-trips
description: Why immutable signal audits must be derived from serialized source artifacts.
---

Compute auditable scores from the persisted canonical CSV representation and build the audit from the persisted signal-history CSV representation.

**Why:** CSV serialization and pandas parsing can change low-order floating-point digits. An audit generated from in-memory downloader values can disagree with a later replay from the immutable files even though the scoring model and source observations are unchanged.

**How to apply:** For refreshed or imported input snapshots, perform the CSV round-trip before scoring and before generating the JSONL audit. Verify the audit against its immutable snapshot before switching any published pointer.