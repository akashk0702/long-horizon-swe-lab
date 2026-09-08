# Maintainer notes: routing regression

This original synthetic task evaluates root-cause debugging across a configuration registry, routing hierarchy, and result cache. Keep this repair analysis separate from candidate instructions in `specification.md`.

## Baseline defect and normal behavior

The baseline passes all 10 developer tests: initial hierarchy selection, direct override replacement, cold lookup after removal, domain errors, registry state, and simple cache operations work. Those tests miss warm fallback lookups followed by broader edits or removals.

The defect has two related boundaries. Configuration notifications identify the scope edited, while cached results are keyed by complete request pairs. Exact-key eviction therefore handles direct tenant-region replacements but misses derived fallback dependencies. Separately, the removal path changes storage without publishing a change. Replacing only the existing eviction expression with a broad clear leaves removal sequences incorrect.

A measured reproduction returned `first=A`, `stored_default=B`, and `next_resolution=A`. The new value was present in the registry; the subsequent resolution returned the earlier value. The evaluator also exercises newly added higher-priority routes, since correctness depends on the absence of higher levels as well as the destination previously selected.

## Measured acceptance results

| Implementation | Developer tests | Evaluator methods | Exit |
| --- | --- | --- | --- |
| Original baseline | 10 passed | 3 passed, 14 failed | 1 |
| Reference overlay | 10 passed | 17 passed, 0 failed | 0 |
| Alternative conservative clear | 10 passed | 17 passed, 0 failed | 0 |

Three separate reference runs returned identical verdicts and counts. UUIDs and elapsed times differed as expected. Baseline, reference, and alternative service packages passed strict mypy in fresh copies. Task-quality tests compare the original task fixture and each prepared source workspace byte-for-byte before and after framework verification.

The 17 evaluator methods use actual API behavior. Multi-entry checks observe results immediately after each mutation, so a later unrelated update cannot mask an incomplete earlier repair. Coverage includes all four hierarchy levels, each removal path, creation of more-specific routes, repeated cycles, independent pairs, missing routes, and multiple live resolvers sharing a registry.

## Reference repair and alternate acceptance

The reference replaces only `registry.py` and `cache.py`. Successful removals publish a change; absent removals keep their existing False result. Every published change advances the receiving cache's generation. Entries store their generation, and lookups discard stale generations before the existing resolver recomputes a destination. Routing precedence remains in the unchanged resolver; no second routing policy or hidden global state is introduced.

The alternative implementation uses an ordinary dictionary and clears it on every delivered change, together with complete removal notifications. It has no generations or versioned entries. Passing the same 17 behavioral methods and 10 developer tests demonstrates that conservative full clearing is accepted. There is no selective-invalidation or performance requirement.

The reference favors understandable correctness over selective reuse. A change costs one generation increment per live cache; a subsequent stale lookup re-evaluates at most four routing scopes. Entries not revisited can remain allocated until clear or the registry/cache lifetime ends. Registry subscriptions retain their caches; disposing of a resolver alone does not unsubscribe its cache. No latency or throughput claim is made.

## Incomplete repair checks

Mutation operators in `tests/test_routing_regression_task.py` create temporary faulty copies. They are task-development probes, not stored candidate solutions. Text replacement is used only to create those probes; the evaluator never inspects candidate source strings.

| Temporary repair fault | Measured evaluator outcome | Representative rejection |
| --- | --- | --- |
| Never invalidate cached results | 2 passed, 15 failed | Cached tenant-region replacement |
| Evict exact tenant-region keys only | 4 passed, 13 failed | Cached global-region replacement |
| Global changes refresh one previously resolved tenant | 15 passed, 2 failed | All affected request pairs must change |
| Cache observer ignores removal events | 11 passed, 6 failed | Removal reveals the current fallback |
| Global region incorrectly outranks tenant default | 12 passed, 5 failed | Normal hierarchy precedence |
| Broad clear on existing set notifications, removal notification still absent | 11 passed, 6 failed | Full cached fallback descent |

All six returned exit 1 with counted behavioral failures. The two removal variants cover different boundaries: one drops a delivered removal event in the cache, while the other never delivers the registry event. The latter is the obvious one-line broad-clear attempt applied to the original baseline. Its rejection does not penalize a complete, functionally correct full-clear design.

## Actual trace excerpts

These lines were rendered from real task-quality runs. Intermediate events and host-specific process details are omitted; the shown order and elapsed values are unchanged. Full runtime artifacts are not published.

Baseline:

```text
00:00.300  PROCESS_COMPLETED  exit=1 timed_out=false
00:00.300  VERIFICATION_COMPLETED  passed=false
00:00.307  WORKSPACE_CLEANED
00:00.344  RUN_FAILED  verification: "Behavioral verification did not pass."
```

Reference:

```text
00:00.263  PROCESS_COMPLETED  exit=0 timed_out=false
00:00.263  VERIFICATION_COMPLETED  passed=true
00:00.269  WORKSPACE_CLEANED
00:00.342  RUN_COMPLETED
```

These are observations, not expected timings. Reproduce current evidence through `long-swe verify` and inspect it with `long-swe replay`.

## Evaluator boundary and limitations

The installed evaluator runs its own fixed unittest class, with the existing strict JSON protocol and framework process controls. Candidate test deletion, fake result files, and printed success documents do not change the baseline's failing outcome; an automated task-quality check verifies this combination. The evaluator does not load candidate pytest hooks or consult the reference overlay.

Before/after source fingerprints can detect persistent evaluator edits. They cannot authenticate the interpreter, stop transient restored changes, or restrict filesystem access. Candidate code shares a Python process with assertions and retains host permissions. This task requires the same cooperative local-code trust as the framework; it does not introduce stronger containment.

There is no concurrent-call guarantee, listener unsubscription API, eviction capacity limit, or persistent configuration store. A cache is scoped to one resolver/registry pairing. The fixture demonstrates a concrete correctness regression and accepts multiple repair designs; broader task difficulty and generalization remain unmeasured.
