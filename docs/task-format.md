# Task format and CLI

A task is one UTF-8 YAML mapping. Schema version `1.0` defaults if omitted; unknown fields and unsupported versions are rejected.

This is a configuration illustration, not a sample engineering task. Save it beside an existing `repository/` directory to validate it. Replace the verifier path with your operator-controlled script before executing `verify`.

```yaml
schema_version: '1.0'
id: local-contract
title: Local task contract
description: Declare a local workspace and a trusted verification entry point.
workspace: repository
timeout_seconds: 30
verification_command: [python, /absolute/path/to/trusted_verifier.py]
allowed_paths:
  - src
  - tests
metadata:
  category: local
environment:
  TASK_MODE: strict
```

## Field contract

| Field | Rule |
| --- | --- |
| schema_version | String 1.0, optional |
| id | Lowercase slug beginning with a letter, single hyphen separators |
| title, description | Nonblank strings |
| workspace | Existing manifest-relative directory, or `.` |
| timeout_seconds | Finite number greater than zero, enforced during execution |
| verification_command | Nonempty argument array, nonblank executable, no NULs |
| allowed_paths | Nonempty explicit workspace-relative file/directory roots |
| metadata | Optional JSON-compatible object, finite numbers |
| environment | Optional validated uppercase TASK_ string parameters |

Workspace/writable paths use slash separators. Absolute/traversal paths, empty segments, device names, nonportable characters, and trailing dots/spaces are rejected. Writable roots cannot be `.`, contain `.git`, or duplicate another root ignoring case. Overlap is allowed. These declarations provide no native write enforcement. Command arguments, including absolute trusted verifier paths, are separate from workspace path fields.

The safe YAML loader rejects anchors, aliases, duplicate/non-string keys, multiple documents, and unsafe tags. Limits are 1 MiB and 32 nesting levels. Quote strings that YAML may interpret as booleans or dates.

## Commands and exit statuses

```sh
uv run --locked long-swe validate path/to/task.yaml
uv run --locked long-swe verify path/to/task.yaml --retain-on-failure
```

| Outcome | Output | Exit |
| --- | --- | --- |
| Help/version | Text on stdout | 0 |
| Valid manifest/workspace | Validation JSON on stdout | 0 |
| Invalid/unreadable manifest or unresolved workspace | Error JSON on stderr | 2 |
| Invalid arguments | Usage text on stderr | 2 |
| Completed verification | Measured TaskResult JSON on stdout | 0 |
| Run or verification failure | Failed TaskResult JSON on stdout | 1 |

Validate checks schema and paths only. It creates nothing and executes nothing. Verify uses a copied workspace and the [JSON verifier protocol](verifier-protocol.md); plain pytest console output is rejected. Options are `--retain-on-failure`, `--temp-parent` (existing directory outside source), `--max-stdout-bytes`, `--max-stderr-bytes`, and `--output-root` (outside the manifest directory). `replay TRACE [--json]` reads saved evidence without execution; `run` remains unavailable.

Library callers can parse with `load_task(Path(...))`, resolve paths with `resolve_workspace(task, manifest_path)`, then call `TaskRunner.verify(task, source)`. Review [execution semantics](execution.md) and [SECURITY.md](../SECURITY.md). Diagnostics/results may include local paths, command arguments, and program output; review before sharing.
