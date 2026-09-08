# Structured trace and replay

`long-swe verify` records actual verification operations as UTF-8 JSON Lines and persists a separate measured result. `long-swe replay` reads stored evidence and never reruns the original command. No candidate editing, file-change events, scoring, or sample tasks are implemented.

## Event schema

Every event uses schema version `1.0` and rejects unknown fields. The common fields are:

| Field | Meaning |
| --- | --- |
| `schema_version` | Required literal `1.0` |
| `run_id` | UUID4, generated once for the run |
| `sequence` | Strict integer, starts at 1 and increments by 1 |
| `event_type` | Explicit EventType enum |
| `timestamp_utc` | Timezone-aware UTC wall-clock timestamp |
| `elapsed_ms` | Nonnegative, finite milliseconds from a monotonic clock |
| `payload` | Pydantic model selected by event type |

Wall-clock timestamps are labels, never duration inputs. The recorder uses `perf_counter_ns`; process and task durations use their existing monotonic timers. Task duration covers workspace preparation through cleanup, while trace elapsed time begins before manifest loading and extends through result persistence. Replay floors elapsed time to whole milliseconds for `MM:SS.mmm` display. This formatting does not claim millisecond timing accuracy. Wall clocks may move backwards; replay preserves sequence order.

## Recorded boundaries

| Event | Emitted when | Payload |
| --- | --- | --- |
| RUN_STARTED | Evidence session starts | Operation (`verify`) |
| TASK_VALIDATED | Manifest/workspace resolution and defensive task validation succeeded | Task ID |
| WORKSPACE_PREPARATION_STARTED | Copy preparation begins | Empty |
| WORKSPACE_PREPARED | Repository, home, and temp directories exist | Relative label `repository` |
| VERIFICATION_STARTED | Behavioral verifier starts | Empty |
| PROCESS_STARTED | Child is launched and process-tree ownership established | Executable basename, omitted argument count, relative cwd |
| PROCESS_TIMED_OUT | Running child crosses the observed deadline | Empty |
| PROCESS_COMPLETED | Child cleanup and output capture finish with an ExecutionResult | Observed exit, duration, timeout, byte counts, truncation flags |
| VERIFICATION_COMPLETED | Verifier returns its interpreted outcome | Pass/fail, nullable counts, duration |
| WORKSPACE_RETAINED | Failure retention is selected for an existing workspace | Relative label |
| WORKSPACE_CLEANUP_STARTED | Workspace cleanup begins | Empty |
| WORKSPACE_CLEANED | Removal returns successfully | Empty |
| RUN_COMPLETED | Completed TaskResult has been persisted | Measured task duration |
| RUN_FAILED | Failed TaskResult, caught stopping error, or result-write failure | Fixed failure category and bounded generic message |

An unsuccessful launch does not emit PROCESS_STARTED or PROCESS_COMPLETED. A timeout emits PROCESS_TIMED_OUT; PROCESS_COMPLETED follows only if cleanup/capture actually finish. A cleanup error emits no WORKSPACE_CLEANED. No events are inferred later from final counts or reconstructed to repair missing history. Event payloads intentionally omit full argv and raw errors.

## Files and location

Default: `<system temporary directory>/long-swe-runs/<UUID4>/trace.jsonl` and `result.json`. The output root can be changed with `verify --output-root PATH`. Resolved output roots must be outside the **entire manifest directory**, a conservative boundary that protects its source workspace even when configuration is malformed. Existing output roots are allowed, but every UUID run directory and trace file is created exclusively. No existing run is overwritten. Output is never stored in the temporary execution copy.

Runs are synchronous. UUIDs and exclusive directory creation prevent accidental collisions between separate invocations; there is no shared-writer or multi-thread recorder API. `.runs/` is ignored for operators using that name elsewhere, but the default output is outside the checkout. Saved evidence has no framework expiration and may be deleted by system-temp maintenance.

`verify` keeps TaskResult JSON on stdout, prints `Artifacts: PATH` on stderr after a returned result, and exits 0/1 according to the behavioral result. Configuration or persistence errors use stderr and exit 2. For errors before a returned result, inspect the selected output root for the run directory; an unavailable root cannot contain an artifact.

Each JSONL record is a complete object followed by a newline. Writes are sequential and flushed after each event, with a maximum of 32 KiB per record including its newline. There is no trace fsync per event. The reader caps total input at 64 MiB and 100,000 events to bound work and memory. The synchronous verification lifecycle produces far fewer records.

`result.json` uses a schema-versioned envelope with the same `run_id`, an `outcome` discriminator, and exactly one of `result` (the exact TaskResult) or `failure` (a typed stopping error). Behavioral failure is still an `outcome: result`; `outcome: failure` means no TaskResult could be constructed. A nullable `trace_error` records incomplete evidence writing. Results are written to a same-directory temporary file, flushed and fsynced, then atomically replaced. The directory itself is not fsynced; filesystem/power-loss durability is not guaranteed.

## Failure evidence

Verifier failures, invalid protocol output, timeouts, launch failures, and workspace failures retain the sequence observed before the failure. Preparation failures can include cleanup of the partial copy without a WORKSPACE_PREPARED event. Retained workspaces remain separate from artifacts and have no cleanup event.

The recorder is an observer, not a verdict authority. At its first write/schema/clock error it stops appending and preserves the written prefix; later observations are not retried or backfilled. The session still attempts to finish verification, clean up, and persist the actual TaskResult with a `trace_error`, then raises a separate TraceWriteError. Result persistence failure emits RUN_FAILED only if the recorder remains writable. Abrupt termination may leave a valid incomplete prefix, a truncated last line, or no artifact. Disk failure can prevent both trace and result persistence; useful evidence is a tested best effort, not an unconditional storage guarantee.

## Reading and replay

```sh
long-swe replay path/to/trace.jsonl
long-swe replay path/to/trace.jsonl --json
```

The reader validates **all** records before rendering. It checks UTF-8, JSON object/schema/payload types, duplicate keys, finite numbers, size limits, a single run ID, contiguous sequence from 1, nondecreasing elapsed time, UTC timestamps, one initial RUN_STARTED, and at most one terminal run event with nothing after it. Corrupt/truncated records produce a structured TraceReadError with a one-based line number. Records are never skipped.

A newline-terminated prefix without a terminal event is valid partial evidence; the human renderer labels it incomplete. A failed run is also a valid trace. Replay returns 0 for valid evidence and 2 for read/validation errors; it does not translate the original run verdict into its own exit status. It does not require the manifest, executable, original workspace, or result artifact.

`--json` emits an array of the validated original event objects, preserving stored values and sequence. It does not merge, reinterpret, or load `result.json`. Human output escapes operator-supplied labels and uses recorded elapsed times, never sorting by wall time. Replay performs file reads and rendering only.

Structural validation is not a full semantic state-machine proof: a hand-edited trace can satisfy the schema, and the reader cannot prove the producer's honesty. The framework emits actual operation observations; traces have no signatures or tamper resistance.

## Privacy

Trace payloads contain no raw environment, arguments, stdout/stderr, or host paths. Process events record only executable basename, argument count, relative cwd, actual byte counts, and completion metadata. There is no preview mode. UUID4 run IDs encode no machine/account identifiers. Failure messages use fixed categories rather than arbitrary exception strings.

The **exact result artifact is not redacted**: it preserves bounded stream diagnostics, configured argv, and paths already present in TaskResult. Task IDs and executable basenames can themselves identify a task. Operators must choose nonsensitive labels and review both artifacts before sharing. Environment filtering prevents arbitrary parent variables from being forwarded, but subprocesses retain host permissions. See [SECURITY.md](../SECURITY.md).

## Verification

Tests execute synthetic temporary verifiers to check successful and failed traces, timeout/launch/copy/cleanup failures, source immutability, retention, measured output counts, artifact linkage, and omission of synthetic parent secrets. Other tests inject I/O failures, reject corrupt records, and disable process invocation while replay runs. Unit-only event fixtures use controlled clocks to test sequence behavior; they are not presented as execution evidence or published run logs.
