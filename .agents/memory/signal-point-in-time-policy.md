---
name: Signal point-in-time policy
description: Availability and live-recording rules for historical and newly observed regime-signal events.
---

Historical reconstruction must never imply that a signal was observable on its original session date. Its availability is no earlier than session close plus six hours, source retrieval, and model computation.

Finalization is a publication gate, not merely a display gate: a Yahoo daily bar seen before the post-close gate can have VIX but no SPX, and its later same-date update must not be frozen as finalized history. Preserve the earlier retrieval as a separate immutable input/legacy signal snapshot rather than silently rewriting it.

**Why:** The original historical availability timestamps were never observed. Using the real reconstruction retrieval and computation times prevents look-ahead and false real-time provenance. Yahoo's daily historical feed also does not attest immutable point-in-time vintages, even when a fresh download includes today's close. A pre-open VIX-only daily row was once published as a signal, then blocked the corrected same-day refresh under the finalized-history guard.

**How to apply:** Mark all Yahoo-derived events `HISTORICAL_RECONSTRUCTION` with `live_recorded=false`, including timely post-close refreshes. Only a separately verified authoritative provider with registered observation timestamps and input vintages may produce `LIVE_REGISTERED`. Operational latest must exclude stale, expired, reconstructed, or insufficient-lineage rows. Do not change old event IDs when adding new metadata contract versions. Only finalized dates enter published signal history; keep original provisional snapshots for provenance and review older-date vendor changes explicitly.