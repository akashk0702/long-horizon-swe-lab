# Maintainer notes: metadata optimization

This original synthetic task separates functional correctness from unnecessary work. The six-module starting package has 210 lines and works through repository, decoder, and processor boundaries. Its 11 developer tests pass. Candidate instructions define observable behavior without prescribing a cache implementation.

## Acceptance evidence

| Implementation | Developer tests | Evaluator passed / failed | Exit |
| --- | --- | --- | --- |
| Baseline | 11 passed | 16 / 3 | 1 |
| Reference | 11 passed | 19 / 0 | 0 |
| Separate preflight/materialization | 11 passed | 19 / 0 | 0 |

Every baseline functional method passes. Its three failures are retrieval-per-distinct-profile, decode-per-distinct-profile, and repeated-profile work in the prefix before a record-validation error. The same count methods also validate all outputs before examining calls. They cover (N, U) values (1, 1), (19, 3), (1000, 8), and (23, 23), so the all-distinct case and varied repeat ratios are explicit.

Three fresh reference verifications returned identical verdicts/counts and distinct run IDs. Task-quality checks compare original fixture and prepared source bytes before and after execution. Baseline, reference, and alternative packages also pass strict mypy.

The small measurement used by task-quality automation actually recorded 1000 records and 8 profiles: baseline gets/decodes = 1000/1000; reference gets/decodes = 8/8. There is no timing-ratio assertion.

## Repair designs and complexity

The reference replaces only `processor.py`. During ordered iteration, a local per-call mapping holds successfully decoded profiles. On a first encounter the existing repository and decoder are invoked, then every record is validated and independently rendered. The mapping ends with the call, so later repository replacements and removals remain visible. No repository/decoder API or error handling changes are needed.

The alternative performs a separate ordered preflight: resolve first encounters and validate each record before a second output-materialization pass. It preserves the first error and avoids resolving later profiles after it. This differs from blindly resolving every distinct profile up front, which could raise a later missing-profile error before an earlier payload-validation error. Both complete designs pass the same external assertions.

If D is profile decoding/validation work and R is per-record validation/copying work, the baseline repeats O(N × D + N × R) work. The reference performs O(U × D + N × R), with O(U) extra profile references in addition to output storage. Dictionary lookup assumptions are the ordinary expected constant-time Python mapping model. Outputs still require allocation and deep copies, so total runtime does not fall in proportion to the decode-count reduction. No artificial delays or busy loops are present.

## Incorrect optimization checks

Temporary variants are produced only in task-quality copies. The evaluator rejects them using observable output/errors/calls, never candidate source matching.

| Incorrect optimization | Evaluator passed / failed |
| --- | --- |
| Cache across enrich calls | 15 / 4 |
| Retrieve once, decode every record | 17 / 2 |
| Decode once, retrieve every record | 17 / 2 |
| Key reuse by record ID | 15 / 4 |
| Return grouped order | 14 / 5 |
| Use one profile for all records | 15 / 4 |

All six exit 1 with counted assertion failures. The persistent cache violates freshness; partial caching misses one work bound; record-ID reuse both repeats work and mishandles duplicate IDs; grouped output changes order and error precedence; single-profile reuse produces incorrect values. Efficiency cases also reject wrong outputs before considering counters. A separate check deletes candidate tests and adds a fake result document, printed success JSON, and an unusable candidate pytest hook: the baseline still fails its three real efficiency cases.

## Measured local workload

The following values were generated from the measurement script's validated JSON output, not estimated. Baseline and reference used identical deterministic input and complete independently generated output expectations. Only `enrich()` is timed with `perf_counter_ns`; generation, process launch, setup, and correctness comparison are excluded. Both implementations include the same lightweight counter wrappers. Separate workers warm up first; each repetition starts with a fresh processor and collaborators. Baseline is measured before reference.

- Python: CPython 3.12.13
- Platform: Windows 11, version 10.0.26200, AMD64
- Records: 10000; distinct profiles: 20
- Profile content: 32 labels, 12 required fields
- Warmups per implementation: 2; measured repetitions: 7

| Measurement | Baseline | Reference |
| --- | ---: | ---: |
| Median milliseconds | 302.5638 | 152.7791 |
| Repository gets per batch | 10000 | 20 |
| Decodes per batch | 10000 | 20 |

Measured median ratio: **1.980400×**.

Baseline samples (ms): 255.4903, 302.5638, 298.4127, 331.24, 284.1884, 320.8316, 319.9924.

Reference samples (ms): 138.3292, 173.9472, 152.7791, 165.046, 144.0562, 172.3735, 140.733.

These measurements characterize this synthetic workload on the reported environment. They are not production performance claims.

No Linux timing figure is claimed here. CI runs the smaller measurement on each platform as a smoke test and gates on exact outputs and work counts. Host load, allocator/GC behavior, metadata size, payload-copy cost, and fixed measurement order affect timings. The seven samples are observations, not a calibrated statistical study. No profiler-derived dominance claim is made.

## Actual trace excerpts

The excerpts below come from real framework runs. Intermediate events and host-specific details are omitted; displayed elapsed values and order are unchanged. Full runtime artifacts are not published.

Baseline:

```text
00:00.388  PROCESS_COMPLETED  exit=1 timed_out=false
00:00.389  VERIFICATION_COMPLETED  passed=false
00:00.395  WORKSPACE_CLEANED
00:00.426  RUN_FAILED  verification: "Behavioral verification did not pass."
```

Reference:

```text
00:00.317  PROCESS_COMPLETED  exit=0 timed_out=false
00:00.317  VERIFICATION_COMPLETED  passed=true
00:00.323  WORKSPACE_CLEANED
00:00.439  RUN_COMPLETED
```

Reproduce fresh traces with `long-swe verify` and inspect them using `long-swe replay`. Replay reads stored evidence and never reruns commands. These timings are observations, not expected durations.

## Trust and limitations

The separately installed evaluator loads its fixed assertion class before candidate imports, injects counters at public collaborator boundaries, suppresses ordinary candidate print output, and emits the existing strict version-1.0 protocol from actual unittest outcomes. It does not discover candidate tests, read candidate result files, or consult the reference implementation. Before/after evaluator fingerprints detect persistent file changes.

Assertions and candidate code still share a Python process with host permissions. Interpreter manipulation, direct OS writes, and restored transient edits are outside this cooperative local-code boundary. The measurement script runs only the supplied baseline/reference in copied workspaces; it is not a containment mechanism.

The task is synchronous, in memory, and requires stable inputs/profiles during a call. It does not implement streaming, concurrent update semantics, bounded output memory, or persistent reuse. Payloads are JSON-compatible values; custom object copying side effects are outside the contract. Difficulty has not been calibrated with participants. This is the third example task; no additional task or framework runtime feature is introduced.
