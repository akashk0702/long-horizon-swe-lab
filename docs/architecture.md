# Architecture and milestone boundary

The foundation separates three concerns: pure contracts, filesystem-aware configuration, and CLI presentation. There are no dependencies from `core` into either `config` or `cli`, and no subprocess calls in application code.

## Implemented layers

| Layer | Responsibility | Boundary |
| --- | --- | --- |
| `core.task` | Versioned Pydantic task schema | No filesystem access or execution |
| `core.state` | Legal lifecycle steps and explicit retry | No persistence or automatic transitions |
| `core.result` | Execution, verification, and terminal report consistency | Caller must provide actual evidence |
| `config.loader` | Bounded UTF-8 YAML parsing and schema diagnostics | Does not inspect the workspace |
| `config.workspace` | Manifest-relative resolution and containment | Read-only snapshot of filesystem paths |
| `cli.main` | Argument parsing, JSON output, exit status | Delegates all validation to the library |

Contracts reject unknown fields to catch spelling mistakes. Numeric measurement fields reject booleans, strings, negative values, NaN, and infinity. Titles and descriptions trim surrounding whitespace; command arguments retain their exact content. Durations represent milliseconds without claiming timing determinism.

## Lifecycle rules

| Current state | Allowed next states |
| --- | --- |
| PENDING | INSPECTING, FAILED |
| INSPECTING | IMPLEMENTING, TESTING, FAILED |
| IMPLEMENTING | INSPECTING, TESTING, FAILED |
| TESTING | IMPLEMENTING, COMPLETED, FAILED |
| FAILED | INSPECTING |
| COMPLETED | None |

Inspection may go directly to testing to establish a baseline. Test feedback can return to implementation. A failed run must restart with inspection; there is no direct retry-to-completion shortcut. A passing verification is additionally required to construct a completed `TaskResult`.

The state function is stateless. A future coordinator will own current state, attempt identity, retry counts, and timestamps. Schema validation alone cannot establish that a caller actually followed a workflow.

## Result semantics

- `ExecutionResult`: captured output, argument vector, exit code, duration, timeout flag. An unobserved exit code is permitted only for a timeout; launch errors will use the future execution exception boundary.
- `VerificationResult`: counted tests, exit code, duration, success, diagnostic messages. Infrastructure failure can have zero tests and no exit code. Failed verification always needs diagnostics. An adapter may reject otherwise passing tests on additional behavioral checks.
- `TaskResult`: terminal state, total measured duration, optional execution records, final verification or failure reason. Intermediate commands may fail during investigation and debugging; a later passing verification may still complete the task.

These models validate consistency, not authenticity. A future verifier must gather results itself and control evaluator inputs. The first milestone has no evaluator adapter or scoring implementation.

## Planned extension boundaries

These components are design intentions, not implemented capabilities:

1. An execution layer will prepare independent workspaces and run explicit argument vectors with a normalized environment, bounded output, and process cleanup after timeouts.
2. A coordinator will apply lifecycle transitions and emit events when operations actually occur.
3. Verifier adapters will collect behavioral test outcomes independently of agent-authored claims.
4. A trace layer will serialize events to JSONL; replay will read them without executing anything.
5. Reporting will combine measured outcomes and diagnostics. Performance tasks will keep environment context and measured timings separate from correctness.

No interfaces are frozen for these later layers. Their security and determinism properties require integration tests when implemented.

## Filesystem and configuration limits

Manifests are limited to 1 MiB and 32 nested YAML container levels to keep configuration parsing bounded. They cannot contain aliases, anchors, duplicate keys, non-string mapping keys, or unsafe construction tags. Datasets belong outside the manifest.

Workspace resolution is relative to the resolved manifest directory. The workspace must exist inside that directory. Allowed writable paths may not exist yet, but any existing symlink resolution must stay within the workspace and outside `.git`. These checks do not create directories or enforce operating-system permissions.

This boundary assumes a trusted local filesystem during validation. A future executor must recheck paths while preparing an isolated copy and must not advertise a local subprocess as protection against hostile code.
