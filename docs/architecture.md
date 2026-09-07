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
| `cli` | Arguments, serialization, exit status | Presentation |

Core contracts do not depend on execution or CLI modules. The adapter separates `build_command(task)` from `parse_result(execution)`. BehavioralVerifier accepts a process runner and adapter; TaskRunner accepts a verifier and workspace options.

## Lifecycle rules

| Current state | Allowed next states |
| --- | --- |
| PENDING | INSPECTING, FAILED |
| INSPECTING | IMPLEMENTING, TESTING, FAILED |
| IMPLEMENTING | INSPECTING, TESTING, FAILED |
| TESTING | IMPLEMENTING, COMPLETED, FAILED |
| FAILED | INSPECTING |
| COMPLETED | None |

The coordinator uses inspection-to-testing. Completion follows passing verification and successful cleanup. It does not perform implementation operations or persist state.

## Outcome compatibility

ExecutionResult keeps its foundation fields. New `stdout_truncated`, `stderr_truncated`, `stdout_decode_errors`, and `stderr_decode_errors` default to false, so old documents still validate.

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

## Deferred work

Candidate operations, persistent events, replay, scoring, and sample tasks remain absent. Protocol validation does not authenticate verifier code. The [trust boundary](../SECURITY.md) is part of the contract.
