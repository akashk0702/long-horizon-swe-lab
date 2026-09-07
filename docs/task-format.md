# Task format and validation CLI

A task is one UTF-8 YAML mapping. Schema version `1.0` is the default; specifying another version fails validation. Unknown fields are rejected.

This is a **configuration illustration**, not an executable sample engineering task. To validate it, save it as `task.yaml` beside an existing `repository/` directory. The command is checked structurally but never executed by `validate`.

```yaml
schema_version: '1.0'
id: local-contract
title: Local task contract
description: Declare the workspace and verification entry point for a local task.
workspace: repository
timeout_seconds: 30
verification_command: [python, -m, pytest]
allowed_paths:
  - src
  - tests
metadata:
  category: local
```

```sh
uv run --locked long-swe validate task.yaml
```

No evaluation scores or test counts are produced. Validation only returns `valid`, `task_id`, `schema_version`, and the resolved `workspace`. Repeating validation against the same unchanged filesystem produces the same output.

## Field contract

| Field | Rule |
| --- | --- |
| `schema_version` | String `1.0`; optional, defaults to `1.0` |
| `id` | Lowercase slug beginning with a letter; single hyphens separate segments |
| `title`, `description` | Nonblank strings |
| `workspace` | Existing directory relative to the manifest, or `.` for that directory |
| `timeout_seconds` | Required finite number greater than zero; enforcement is deferred |
| `verification_command` | Nonempty argument array; first argument is a nonblank executable; no NULs |
| `allowed_paths` | Nonempty array of explicit workspace-relative files or directory roots |
| `metadata` | Optional JSON-compatible object with finite numeric values |

Paths use `/` separators on every supported host. Absolute paths, traversal segments, empty segments, device names, Windows-reserved characters, and trailing dots/spaces are rejected. Writable roots cannot be `.`, contain `.git`, or duplicate another root ignoring case. Overlapping parent/child roots are allowed; each root denotes a whole subtree once write enforcement is implemented. These declarations currently provide no write permission enforcement.

Arguments after the executable may be empty or contain spaces. Shell expansion, environment-variable interpolation, pipelines, and shell-string parsing are not performed. Executable availability is not checked in this milestone.

YAML uses PyYAML's safe loader. Quote scalar values that YAML may interpret as booleans or dates when strings are intended. Anchors, aliases, duplicate keys, and multiple documents are not accepted.

## CLI behavior

| Invocation or outcome | Output | Exit status |
| --- | --- | --- |
| `long-swe --help` | Usage text on stdout | 0 |
| `long-swe --version` | Installed package version on stdout | 0 |
| Valid manifest and workspace | One JSON object on stdout | 0 |
| Invalid/unreadable manifest | JSON `TaskConfigError` on stderr | 2 |
| Missing/escaping workspace path | JSON `WorkspaceError` on stderr | 2 |
| Invalid arguments or unavailable command | Usage text on stderr | 2 |

Library callers can use `load_task(Path(...))` for schema-only validation, then `resolve_workspace(task, manifest_path)` for filesystem checks. Both expose subclasses of `LabError` for expected failures. The CLI avoids dumping manifest values in errors, but field names and local paths can appear; review diagnostics before sharing them.
