# Controlled local execution

## Workspace lifetime

`prepare_workspace` creates `long-swe-*` under the system temporary directory or an operator-selected `temp_parent`. The parent must exist outside the source tree. Each run contains `repository/`, `home/`, and `tmp/`. Cleanup checks that the run root still belongs to that parent.

Files are independently copied, never hardlinked. Copies receive owner read/write access plus source executable bits; timestamps, ACLs, read-only flags, and privileged mode bits are not reproduced. Symlinks, junctions, other Windows reparse points, sockets, FIFOs, and devices are rejected. Configuration validation may accept internal links, but execution copying is stricter.

Excluded names at every level: `.git`, `.venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.env`, and `.env.*`. Git metadata cannot be included in this milestone. Default preparation limits are 10,000 regular files and 256 MiB copied content, configurable through `WorkspaceOptions`. They do not limit command-created files or process memory.

The workspace starts in a failed state and is marked successful after passing verification. Normal failures clean up unless `retain_on_failure=True`. Retained paths appear in failed reports. Preparation errors remove partial copies. Cleanup errors are surfaced, not ignored. Retention has no expiration; operators must remove artifacts when finished.

## Invocation and timeout

`ProcessRunner.run(argv, cwd=..., environment=..., timeout_seconds=...)` validates arguments and calls Popen with `shell=False`, explicit cwd/environment, closed stdin, closed extra handles, and binary pipes. Empty arguments are preserved. No shell interpolation occurs. The low-level runner requires an appropriate cwd from its caller; TaskRunner owns copied workspace preparation.

Bare executables are resolved using the controlled PATH, with the running interpreter's directory first. Windows accepts native `.exe`/`.com` programs and rejects batch files to prevent implicit shell invocation. Use an explicit interpreter for scripts. Explicit executable paths are trusted configuration and may lie outside the copy.

Timing uses `perf_counter` starting just before launch. A running command exceeding its timeout is terminated immediately; there is no graceful-signal interval. Polling sleeps up to 5 ms when no output is ready. OS process-creation calls themselves are not interruptible by this timer.

Linux commands start a new session/process group. Cleanup sends SIGKILL to the group and reaps the direct child. Windows children start suspended, are assigned to a kill-on-close Job Object, then resume through Win32 thread APIs. Cleanup terminates the job, waits for zero active processes, and reaps the child. Ownership setup failure aborts execution rather than falling back to untracked processes. Background descendants are cleaned after normal leader exit too.

`ProcessOptions.cleanup_timeout_seconds` defaults to 5 seconds. Job termination, direct-child reaping, and final pipe drainage have bounded cleanup waits, so total duration can exceed the task timeout. Cleanup failure is an error. Cancellation during setup/capture also invokes cleanup; abrupt OS termination cannot execute Python finally blocks.

## Output capture

Python 3.12 nonblocking pipe reads work on both supported OSes. Finite drain batches allow both streams and the timeout clock to progress. Retention uses byte prefixes: 1 MiB stdout and 256 KiB stderr by default, independently configurable down to zero. Excess bytes are drained and discarded without growing retained memory or deadlocking verbose processes. There is no unlimited spool file.

Truncation flags indicate a byte limit was exceeded or EOF was not observed by the final drain deadline. Invalid UTF-8 uses U+FFFD replacement and a separate decode-error flag. A byte limit can split a multibyte character. Retained bytes and decoded strings use memory proportional to configured limits, not total output.

The JSON adapter rejects truncation of either stream and invalid UTF-8 stdout. Stderr is diagnostic text; replacement decoding there alone does not invalidate a complete protocol message.

## Environment

The builder constructs a fresh mapping. Parent inputs are only PATH and, on Windows, SYSTEMROOT/WINDIR. Empty/relative PATH entries are removed and the current interpreter directory is prepended. Those tool directories are trusted host inputs, not a hermetic dependency bundle.

HOME/USERPROFILE and TMP/TEMP/TMPDIR point to fresh run directories. Windows APPDATA/LOCALAPPDATA also point inside the fresh home. Parent Python path overrides, proxy settings, arbitrary task parameters, and credential variables are not inherited.

Fixed values: `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8:replace`, `PYTHONHASHSEED=0`, `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`, `LC_ALL=C`, `LANG=C`, and `TZ=UTC`. Programs may ignore these; Windows programs do not uniformly honor TZ or POSIX locales.

Manifest environment parameters must use uppercase `TASK_` names and strings without NULs. Credential-like names and process-control overrides are rejected. Do not put sensitive values in task parameters. Tests use a synthetic parent sentinel to prove arbitrary variables are not forwarded. Direct ProcessRunner callers explicitly supply their mapping; TaskRunner always uses the controlled builder.

## Limitations

The source must stay stable while copying; this is not a race-resistant hostile-filesystem copier. Programs retain host permissions and network access and can explicitly read host files regardless of environment filtering. POSIX descendants can detach into a new session and escape group cleanup. Linux init may retain terminated descendants briefly as zombies. Windows nested-job restrictions can cause setup failure. No privilege separation or command memory/CPU/disk quotas exist.

The framework provides deterministic evaluation contracts and controlled execution; determinism of evaluated programs remains task-dependent.

Implementation uses Python's [nonblocking pipe API](https://docs.python.org/3.12/library/os.html#os.set_blocking) and documented Windows [Job Object ownership](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).
