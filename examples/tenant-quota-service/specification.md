# Tenant-aware active-job quotas

Add tenant-aware active-job quota enforcement to an existing job-processing service while preserving its public API and current scheduling behavior.

The repository under `start/` is functional. It has no quota feature. Work on a copy of that repository. Choose your own internal design; evaluation checks observable behavior, not implementation similarity.

## Existing API to preserve

`job_service` exports `JobService`, `ServiceConfig`, `JobStatus`, `Job`, and `InMemoryJobRepository`. `JobService(repository=None, config=None)` supports:

- `submit_job(tenant_id, payload)` returns an immutable PENDING Job.
- `get_job(job_id)` returns the current snapshot, or raises `JobNotFoundError` with `job_id`.
- `list_jobs(tenant_id=None)` returns a tuple in insertion order, optionally filtered by exact tenant ID.
- `set_status(job_id, status)` returns a new snapshot and leaves old snapshots unchanged.

Jobs have `id`, `tenant_id`, `status`, and a string-to-string `payload` mapping. Payload inputs are copied. IDs use the configured `id_prefix` and a repository-local increasing integer, starting at 1. Tenant IDs must be nonblank strings; whitespace is not normalized. Invalid submissions raise ValueError before changing storage. Unknown status values raise ValueError.

PENDING may become RUNNING or CANCELLED. RUNNING may become SUCCEEDED, FAILED, or CANCELLED. Repeating a status is allowed and idempotent. Terminal jobs cannot reopen; other transitions raise `InvalidTransitionError`. Keep these scheduling rules and existing exception behavior.

## Configuration extension

Extend the existing `ServiceConfig` public constructor with:

| Argument | Contract |
| --- | --- |
| `default_active_job_limit` | Integer, defaults to **3**, must be nonnegative |
| `tenant_active_job_limits` | Optional mapping from nonblank tenant IDs to nonnegative integer limits; defaults to an empty mapping |

Here “optional” means the argument may be omitted; explicit `None` is not required. Booleans and non-integers are invalid limits. Invalid defaults or any invalid override must raise ValueError at configuration construction, even if that tenant has not submitted a job. Preserve `id_prefix` and its validation.

Treat configuration as a construction-time snapshot: later mutation of the caller's overrides dictionary must not reconfigure the service. Runtime reconfiguration is out of scope. An override applies by exact tenant ID and replaces the default, including when its value is zero.

For example, a default of 3 and overrides `{"premium-a": 10, "suspended-b": 0}` permit ten active jobs for `premium-a`, none for `suspended-b`, and three for other tenants.

## Submission rules

1. Active jobs are **exactly PENDING and RUNNING**. SUCCEEDED, FAILED, and CANCELLED are terminal and do not count.
2. For a valid submission, use that tenant's applicable limit and current repository state. Accept only when `active_count < limit`.
3. At or above the limit, raise `job_service.errors.QuotaExceededError`. It must be a domain Exception with `tenant_id`, `limit`, and `active_count` attributes; its message must identify the tenant and limit. Exact message wording and superclass are not prescribed.
4. Rejection must not persist a job, consume an ID, change ordering/payloads/statuses, or otherwise alter existing jobs.
5. Quotas are independent across tenants. Moving an active job to a terminal state releases capacity immediately; moving PENDING to RUNNING does not release capacity.
6. Callers must not count jobs themselves. State already present in an injected repository counts, including changes made through another service sharing that repository. All calls in this task are sequential.
7. Invalid tenant IDs/payloads still raise ValueError before quota enforcement. Preserve all behavior outside the newly requested quota restriction.

## Boundaries

You may change or add code under `src/` and add developer tests. Do not remove existing API behavior or developer tests. The repository remains in-memory and single-threaded. No persistence layer, web server, concurrent submission guarantee, custom scheduling policy, or runtime configuration reload is required.

Evaluator-owned behavioral verification is kept outside the candidate workspace. It is public and inspectable, but it is not part of the solution and must not be modified. The verifier runs its own behavioral assertions; candidate-created reports, deleted developer tests, or source-code resemblance are not evidence of correctness. Do not modify the evaluator, framework, task manifest, or reference files.
