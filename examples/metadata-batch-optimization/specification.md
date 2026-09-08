# Optimize repeated metadata work

Optimize repeated metadata decoding in a batch enrichment pipeline while preserving ordering, validation, and error semantics.

## Existing system

`BatchProcessor(repository, decoder).enrich(records)` accepts a stable sequence of `InputRecord` values and returns a list of `EnrichedRecord` values. Each record names a metadata profile. The repository provides encoded profile strings; the decoder produces a `MetadataProfile`; enrichment copies the payload and adds the category, version, and labels. The starting system is functionally correct and its developer tests pass.

The service uses `repository.get_encoded(profile_id)` and `decoder.decode(profile_id, encoded)` through public protocols. Callers can supply compatible collaborators. Their returned metadata remains authoritative; do not bypass either collaborator or replace decoding with assumptions about particular profile IDs.

## Required behavior

- Preserve all public exports, constructor signatures, and method signatures.
- Preserve input order, length, record IDs, profile IDs, payload values, category, version, and label order, including duplicate labels.
- Duplicate record IDs and repeated references to the same InputRecord are allowed: preserve every occurrence independently. Record IDs are not deduplication keys.
- Do not mutate the input sequence or records. Each output owns its own deep payload snapshot and label list. Mutating one output must not change another output, an input, or a later call's result.
- An empty batch returns `[]` without repository or decoder calls.
- A required payload field is satisfied by its key's presence, including when its value is null. Preserve the order of missing fields declared by the profile.
- Supported payloads are dictionaries with string keys and JSON-compatible nested values. Inputs, collaborator behavior, and profiles remain stable during one call. Concurrent mutation and arbitrary objects with custom copying behavior are outside the task.

## Errors and processing order

Process records in input order for observable error behavior. For each record, profile resolution/decoding precedes required-payload-field validation. Raise the first error without returning partial output. Do not resolve profiles belonging only to records after the first failing record. Never suppress validation or substitute a default profile.

| Failure | Error | Required attributes and message |
| --- | --- | --- |
| Unknown profile | `MissingProfileError` | `profile_id`; `Profile not found: ID` |
| Invalid JSON syntax | `ProfileDecodeError` | `profile_id`; `Invalid JSON for profile: ID` |
| Invalid decoded structure | `ProfileValidationError` | `profile_id`, `reason`; `Invalid profile ID: REASON` |
| Missing payload fields | `RecordValidationError` | `record_id`, `missing_fields` tuple; `Record ID missing fields: FIELD1, FIELD2` |

The JSON decoder's object has exactly `category`, `version`, `labels`, and `required_fields`. Category is a nonblank string; version is a positive integer, not a boolean; both list fields contain nonblank strings. Empty lists are allowed, and values are not stripped or normalized. Preserve the existing decoder's validation order, reasons, and standard-library JSON interpretation. Its implementation and developer tests document those existing diagnostics.

## Observable efficiency contract

During **one** `enrich()` invocation, successfully resolving a profile that has already been resolved must not require another repository retrieval or decode. For a successful batch of N records referencing U distinct IDs, the injected repository and decoder must each observe exactly U calls, one for every referenced ID. This includes N=U and noncontiguous repeats.

On failure, the same limit applies to the processed prefix: each encountered ID is retrieved at most once and decoded at most once, with decoding occurring only after a successful retrieval. Stop on the first error described above. A failing record can use already resolved metadata, but its own payload must still be validated. No collaborator calls are permitted for profiles first referenced strictly after that error.

For example, 1,000 valid records using eight distinct profiles require eight retrievals and eight decodes. The starting implementation performs 1,000 of each. These are work-count requirements, not elapsed-time thresholds. Outputs and errors are evaluated alongside counts.

## Lifetime and freshness

Each invocation must observe the repository state for that invocation. A set, replacement, or removal between calls must be reflected immediately by the next call, even when reusing the same BatchProcessor. Retaining stale metadata across calls is incorrect. Cross-call reuse is not required.

The contract does not prescribe a class, dictionary name, helper, cache layout, or algorithm. Any design satisfying the functional, error-ordering, collaborator, and work-count requirements is accepted.

## Reproduction and acceptance

After the root repository's `uv sync --locked`, prepare an external copy as described in this task's README. Run the developer tests from that copy and use `long-swe verify path/to/copy/task.yaml` to run external evaluator-owned verification. The evaluator uses actual API behavior and instrumented collaborators. Candidate-generated result files and console success claims are not acceptance evidence.

Use the separate measurement script to inspect actual timing on the supplied synthetic workload. Timing ratios are supporting evidence; deterministic correctness and operation counts decide acceptance. Keep evaluator, reference, and measurement code outside the candidate workspace.
