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

Report defects using minimal reproductions without sensitive data. Tests and documentation should use independently created fixtures.
