# Clone source extraction error recovery

Updated 2026-10-17. User clarification: five minutes is an estimate, not a cutoff. A legitimate Work session taking longer must continue normally.

The existing 900-second response timeout, quota/pool waiting rules and retry count remain unchanged. No new busy-without-progress watchdog or five-minute extraction deadline is applied. Prompt content and the artwork/idea/grid workflow remain unchanged.

Changes:

- File download failures are recorded instead of silently skipped. Network transfers use the browser-context request client with the same cookies and a timeout, avoiding an unbounded Download.path() wait for remote transfers.
- File-download work has an aggregate 120-second budget rather than waiting up to 120 seconds independently for every link. Normal ChatGPT Work processing is separate from this download budget.
- Broken download links get one repair request in the same chat. The request explicitly reuses the artwork already extracted, without returning to the product page or drawing new artwork.
- Failed link repair raises a transient error for the existing account/session retry mechanism. A partially downloaded set is not published as complete while known transfer errors remain. Repeated returned files are deduplicated.
- Invalid ZIP behavior remains: request a valid replacement in the same chat, then use the existing recovery path if still invalid.
- Every source attempt records start, request, result, download errors, save completion or exception in source_fetch.jsonl under its source/item directory. Entries contain account, timestamp and elapsed seconds.
- Source account acquisition logs separate time spent waiting for a free account. Busy pool waiting is not counted as a failed extraction.
- UI-launched task output is retained with timestamps in projects/_nhat_ky/<task-id>.log (under the configured projects directory). The in-memory 3,000-line cap does not truncate the disk log. File-write failure is reported in the task API without stopping generation.

Verification includes simulated Work taking over seven minutes without failure, stopped replies without files, link repair and deduplication, rejection of incomplete failed downloads, bounded HTTP file transfer and durable timestamped logs beyond the memory cap. No new live ChatGPT extraction was run for this change.

Restart the UI backend to activate durable logging in that server process. New clone subprocesses load the source-extraction changes immediately. Existing running processes retain their loaded code. No installer was rebuilt.

## 2026-10-18: unsent prompt recovery

An observed run retried four fresh sessions on acc1 without sending the source prompt.
Unpinned clone stages now rest that account briefly and try another account when the prompt
cannot be sent, within the existing retry limit. Legacy pinned planners retain their account.
The chat sender re-resolves and clicks the current Send button for its retry instead of relying
only on Enter, which can behave differently after switching to Work. An acknowledged send is
not submitted again. Exact English/Vietnamese Send controls take precedence over fuzzy labels.

A direct live source extraction subsequently completed in 247 seconds and saved 12 artworks
from the returned ZIP. Mixed clone/idea end-to-end measurement is recorded separately under
`.cache/live-mixed-20261018/`; completion and account utilization must be based on that run,
not inferred from the unit tests. No installer has been rebuilt.
