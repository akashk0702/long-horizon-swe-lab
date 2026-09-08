# Architecture and ownership

| Layer | Responsibility | Owned resources |
| --- | --- | --- |
| `core` | Contracts, lifecycle, exceptions | No I/O |
| `config` | YAML and manifest-relative paths | Read-only input access |
| `execution.workspace` | Copies, limits, cleanup, retention | One temporary run root |
| `execution.environment` | Allowlisted host inputs, fresh home/temp | New environment mapping |
| `execution.process` | Explicit argv, capture, timing | Direct child and pipes |
| `execution.timeout`, `_windows` | Descendant ownership/termination | POSIX group or Windows job |
| `evaluation` | Trusted verifier execution and explicit protocol | Adapter and observed outcomes |
| `execution.runner` | Copy → verify → cleanup → final result | Run lifetime |
| `tracking.event`, `tracking.observer` | Typed observations and observer interface | No I/O |
| `tracking.recorder`, `tracking.artifacts` | Sequential records and atomic result envelopes | Run output directory |
| `tracking.reader`, `tracking.replay` | Bounded validation and evidence rendering | Read-only trace access |
| `application.verification` | Evidence lifetime, including pre-result failures | Recorder and artifact store |
| `cli` | Arguments, serialization, exit status | Presentation |

Core contracts do not depend on execution or CLI modules. The adapter separates `build_command(task)` from `parse_result(execution)`. BehavioralVerifier accepts a process runner and adapter; TaskRunner accepts a verifier and workspace options.

Execution and evaluation depend only on typed events and the observer interface. They do not import file recording, replay, or the application session. The CLI's `verify_manifest` session creates artifacts before configuration loading, supplies a recorder to TaskRunner, and writes the measured result after cleanup. The lower-level `TaskRunner.verify` API retains an optional observer and does not persist artifacts by default.

## Lifecycle rules

| Current state | Allowed next states |
| --- | --- |
| PENDING | INSPECTING, FAILED |
| INSPECTING | IMPLEMENTING, TESTING, FAILED |
| IMPLEMENTING | INSPECTING, TESTING, FAILED |
| TESTING | IMPLEMENTING, COMPLETED, FAILED |
| FAILED | INSPECTING |
| COMPLETED | None |

The coordinator uses inspection-to-testing. Completion follows passing verification and successful cleanup. It reports actual boundaries to its observer; it does not perform implementation operations or own persistence. The session records terminal run events after result persistence. Trace recording errors cannot rewrite the behavioral verdict.

## Outcome compatibility

ExecutionResult keeps its foundation fields. New `stdout_truncated`, `stderr_truncated`, `stdout_decode_errors`, and `stderr_decode_errors` default to false, so old documents still validate.

`stdout_bytes_observed` and `stderr_bytes_observed` are additive nullable fields for compatibility with older documents. ProcessRunner always fills them from actual pipe reads, including bytes discarded beyond capture limits. They are not estimates of bytes a process intended to write.

VerificationResult accepts either two strict nonnegative integer counts or two null counts. Null means unavailable evidence, such as malformed output or launch failure. Partial/negative/coerced counts and success without observed passing tests remain invalid. Consumers must handle null explicitly instead of treating it as zero.

TaskResult adds an optional `retained_workspace` for failed runs. Process durations measure launch, lifetime, capture, and cleanup using a monotonic clock. Task duration also includes workspace preparation and cleanup. Measured timings may differ between runs.

## Failure boundaries

- Configuration errors fail before execution.
- Copy failure removes the partial copy; no command starts.
- Launch/setup failure produces ProcessLaunchError with measured duration and no invented exit code.
- Capture/cleanup failure produces ProcessError and cannot claim successful verification.
- Protocol failure preserves execution diagnostics and leaves test counts unknown.
- Explicit failure retention preserves prepared workspaces. Incomplete preparation copies are removed.
- Cleanup errors invalidate completion even if behavioral assertions passed.
- A failed run still has its observed events and either the exact TaskResult or a structured pre-result failure artifact.
- Recording failure stops further appends without backfilling. The result envelope marks incomplete recording, and a separate TraceWriteError surfaces the evidence failure.
- If output storage cannot be created/written, some or all evidence may be unavailable. No success event is synthesized to fill a gap.

## Deferred work

Candidate operations, scoring, and sample tasks remain absent. Protocol validation does not authenticate verifier code. The [trust boundary](../SECURITY.md) and [trace semantics](tracing.md) are part of the contract.
