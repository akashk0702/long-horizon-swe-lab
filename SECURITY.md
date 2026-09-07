# Security and trust model

This project provides process isolation by workspace separation and controlled invocation. It is **not a VM, container sandbox, or protection against malicious native code, kernel/system attacks, or hostile local users**.

## Required trust

The operator must trust manifests, executables, verifier code/assertions, installed tools, and the host filesystem during copying. Do not execute untrusted code on a host containing valuable credentials or data. Protocol validation cannot establish verifier provenance or prove that a self-reporting program performed independent tests.

Core tests require no network APIs or credentials. The controlled environment does not inherit arbitrary parent variables. Nevertheless, subprocesses retain the host user's permissions: they can open host files, locate real profiles, access the network, or invoke tools with their own defaults. Environment filtering is not access control.

## Implemented controls

- Fresh regular-file copies without Git metadata, environment files, virtual environments, or links.
- Copy limits, destination containment checks, and run-root checks before cleanup.
- Explicit arguments/cwd, no implicit shell expansion, closed stdin, and bounded output.
- Process-group/Job Object cleanup after timeout and normal leader completion.
- Strict protocol validation, rejection of contradictory/incomplete evidence, and unknown counts when evidence is unavailable.

## Boundaries

`allowed_paths` is validated but does not restrict native writes. Framework preparation/cleanup does not modify source files; a malicious program can still address them by an absolute path. Concurrent path replacement is outside the copier's trust model. Detached POSIX processes can escape cleanup; Windows job assignment can be restricted by the host. Resource quotas and automatic dependency provisioning are absent.

Captured output, command arguments, and retained workspaces can contain data emitted by tools. Review them before sharing. Retention is opt-in with no expiration. Do not put sensitive values in manifests or task environment parameters.

## Trace and result privacy

CLI verification persists `trace.jsonl` and `result.json` outside both the manifest directory and copied workspace. Output directories use random UUID4 names; no account or machine identifiers are encoded. POSIX run directories request owner-only permissions. Windows relies on inherited directory ACLs, so choose an output root with suitable access controls. Path checks assume a trusted, stable filesystem.

Traces contain metadata only: task ID, executable basename, omitted argument count, relative workspace label, observed byte counts, timing, and verdicts. They exclude full command arguments, stdout/stderr, environment mappings, host paths, and raw exception messages. Task IDs and executable basenames remain operator-supplied labels; they are not automatically anonymized. There is no output preview mode.

`result.json` is different: its versioned envelope preserves the exact TaskResult, including bounded stdout/stderr, configured argv, diagnostics, and any retained workspace path. It is **not redacted**. Keeping it outside the source tree prevents accidental source modification, not disclosure. Review artifacts before sharing; remove retained evidence when no longer needed. The default system-temp output directory may also be removed by OS maintenance.

Traces are editable structured evidence, not cryptographic audit logs. Validation checks syntax, schemas, sequence, timing order, and terminal boundaries; it cannot authenticate a process or prove verifier assertions were honest. Replay never executes the recorded command. Missing/truncated records are not repaired or silently skipped.

Report defects using minimal reproductions without sensitive data. Tests and documentation should use independently created fixtures.
