# Batch/pool audit — 2026-10-16

## Changes from this audit

- Waiter cancellation no longer waits up to 30 seconds for the cross-process gate while holding the local mutex. Account release remains responsive when another process owns that gate.
- Cancellation that cannot obtain the gate is retained locally and flushed during the next acquisition/cancellation. If the process dies, dead-owner cleanup remains authoritative.
- A locked status file cannot abort the remaining clone batch. Errors escaping before a stage starts receive bounded retries using `crash_retry_waits_s` (default 30/90 seconds), scheduled without blocking the other books or AI/postproduction executors.

## Verified paths

| Area | Cases |
|---|---|
| Ownership | Multiple processes compete for 40 profiles; global/per-mode caps; no duplicate profile ownership |
| Waiting | Normal idea/clone contention preserves progress; external locks and quota have separate limits; stopped work clears waiter IDs |
| Release | Success, temporary errors, timeout, RAM pressure, locked files, page failure, quota, explicit stop/yield, interruption, and context-close errors |
| Recovery | Process dies while holding an OS lease; stale lease metadata; corrupted/written-partial images; source-reference commit failure |
| Resume | Completed files remain; only missing work runs; downloaded candidates are rechecked after verification network/JSON errors |
| Scheduling | Two clone books share a small Chrome budget; idle capacity shifts to the remaining book; postproduction does not block new artwork; queued books survive worker errors |
| Idea batches | Randomized failures, all accounts temporarily out of quota, low browser capacity, crash then rerun, pause/restart and multiple queued topics |
| Planning | One account/chat commits the entire clone plan before drawing; resume stays in that chat; a missing chat stops planning clearly |

## Evidence

- Final clone regression: **154 tests passed** (`batch-audit-final-clone.log`).
- Final idea/batch/pool/chat suite: **112 tests passed** (`batch-audit-final-idea-pool.log`).
- Additional release fault matrix, including context-close errors: **3 tests passed**, with subcases for 10 failure types at session-open and work boundaries (`batch-audit-close-release.log`).

Logs are saved under `.cache/batch-audit-*.log` and `.cache/pool-cleanup-deferred-tests.log`. Browser/model work in the stress tests is simulated; profile OS locks, cross-process allocation, waiter files and scheduler code are real. These tests do not constitute a live run with 40 ChatGPT accounts and do not guarantee external service response time.

Existing worker processes retain their loaded code. The changes take effect on a new start/resume; files and existing plans are preserved.
