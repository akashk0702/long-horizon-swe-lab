# Task development and validation

All service code, task wording, behavioral checks, and reference changes were authored independently for this synthetic exercise. The reference overlay is used to establish solvability; it is not supplied inside the candidate workspace or consulted by the verifier.

## Acceptance evidence

| Workspace | Existing pytest cases | Evaluator methods | Verifier exit |
| --- | --- | --- | --- |
| Unmodified starting repository | 11 passed | 1 passed, 13 failed | 1 |
| Fresh start plus reference overlay | 11 passed | 14 passed, 0 failed | 0 |

The baseline's existing-API compatibility case passes. Its quota cases fail because the new configuration and submission restriction are absent. This distinguishes a feature request against functioning software from a broken starting project. Three separate reference verification runs produced the same verdict and counts. Durations and UUIDs are measured independently and are expected to differ.

The reproducible task-quality checks live in `tests/test_tenant_quota_task.py` at the framework root. They use copied workspaces, actual ProcessRunner/TaskRunner execution, strict protocol parsing, persisted traces, and byte comparisons of source fixtures. The developer checks execute pytest and strict mypy against both the start and completed reference copy. No human pytest output is parsed to manufacture verifier counts.

## Weak-implementation checks

These are mutation operators in the task-development tests, applied only to temporary copies of the reference. No faulty candidate solutions are stored in the task package. Text replacement identifies a development mutation site; **acceptance verification itself never matches source strings**.

| Deliberate fault | Measured evaluator result | Example rejecting case |
| --- | --- | --- |
| Count every historical job | 10 passed, 4 failed | Every terminal status releases capacity |
| Count jobs globally | 12 passed, 2 failed | Tenant independence |
| Reject only above the limit | 3 passed, 11 failed | Configured default and exact boundary |
| Persist before rejection | 3 passed, 11 failed | Rejection preserves state and IDs |
| Ignore tenant override | 11 passed, 3 failed | Overrides in both directions |

All five returned exit 1. The automated assertions require failure of the relevant behavioral case, not just a process error. Mutation operators fail clearly if their intended edit site changes; they do not silently turn into ineffective checks.

## Reference design

The overlay replaces `config.py`, `errors.py`, and `service.py` only. Configuration validates every limit at construction and copies the override mapping into a read-only snapshot. A domain exception carries the rejected tenant, applicable limit, and observed active count.

Submission validates existing input requirements first, resolves the tenant's limit, counts PENDING/RUNNING snapshots through the repository interface, and rejects before creation. No cached count or new global state exists. Status changes therefore release capacity immediately, including sequential changes through a shared repository. Repository implementation and scheduling rules remain unchanged.

This design trades an O(N) scan over repository history per submission for a small, easily audited correctness surface. No speed measurements or scalability claims are made. An indexed implementation could also satisfy the contract if it preserves all behavior and state consistency.

## Actual trace excerpts

These excerpts were rendered from real local task-quality runs. Intermediate lines and host-specific process details are omitted; event order and elapsed values below are unchanged. Full runtime artifacts are not published.

Baseline:

```text
00:00.266  PROCESS_COMPLETED  exit=1 timed_out=false
00:00.266  VERIFICATION_COMPLETED  passed=false
00:00.275  WORKSPACE_CLEANED
00:00.312  RUN_FAILED  verification: "Behavioral verification did not pass."
```

Reference:

```text
00:00.319  PROCESS_COMPLETED  exit=0 timed_out=false
00:00.320  VERIFICATION_COMPLETED  passed=true
00:00.327  WORKSPACE_CLEANED
00:00.446  RUN_COMPLETED
```

These timings are observations, not targets or performance comparisons. Reproduce your own traces with the README commands and inspect them with `long-swe replay`.

## Evaluator review and limits

The evaluator is installed from this task's separate local package by the root development environment. It loads only its own fixed test case class, before importing candidate code. Candidate pytest configuration/hooks are not loaded. Ordinary candidate stdout/stderr are redirected during tests, so printed success JSON cannot replace the evaluator's protocol. Candidate result files are never read.

Task-quality tests demonstrate that an unchanged baseline still fails after its developer tests are deleted, a fake result file is added, and a success document is printed during import. Another test modifies a **disposable copy** of the installed evaluator and confirms integrity failure is rejected with unknown counts. It does not modify the real evaluator installation.

Before/after source fingerprints and a complete-test-run check catch ordinary persistent tampering or incomplete execution. They do not authenticate the interpreter, prevent native writes, or protect against transient changes restored before checking. Candidate code runs in-process with unittest and retains host permissions. The operator must trust the local code sufficiently for this execution model. The framework's existing security boundary is unchanged.

There are no inaccessible tests, participant results, performance claims, concurrent execution guarantees, or externally calibrated difficulty measurements in this task.
