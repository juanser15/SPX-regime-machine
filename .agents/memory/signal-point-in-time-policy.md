---
name: Signal point-in-time policy
description: Availability and live-recording rules for historical and newly observed regime-signal events.
---

Historical reconstruction must never imply that a signal was observable on its original session date. Its availability is the later of session close plus six hours and the source snapshot's actual retrieval time.

**Why:** The original historical availability timestamps were never observed. Using the real reconstruction retrieval time prevents look-ahead and false real-time provenance.

**How to apply:** Mark reconstructed events `HISTORICAL_RECONSTRUCTION` with `live_recorded=false`. A scheduled refresh may mark only its newest session `LIVE_REGISTERED`, and only when retrieved within 36 hours after that session's close; delayed gap rows remain reconstructions.