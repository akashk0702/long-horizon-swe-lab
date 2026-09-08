"""Run explicit argument vectors with bounded, nonblocking pipe capture."""

import os
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO

from pydantic import TypeAdapter

from long_horizon_swe.core.exceptions import ProcessError, ProcessLaunchError
from long_horizon_swe.core.result import ExecutionResult
from long_horizon_swe.core.types import Command, PositiveSeconds
from long_horizon_swe.execution.options import ProcessOptions
from long_horizon_swe.execution.timeout import ProcessTree
from long_horizon_swe.tracking.event import (
    EmptyPayload,
    EventType,
    ProcessCompletedPayload,
    ProcessStartedPayload,
)
from long_horizon_swe.tracking.observer import NullObserver, Observer


class _Capture:
    def __init__(self, stream: IO[bytes], limit: int) -> None:
        self.stream = stream
        self.limit = limit
        self.data = bytearray()
        self.truncated = False
        self.eof = False
        self.observed = 0
        os.set_blocking(stream.fileno(), False)

    def drain(self) -> bool:
        active = False
        # A finite batch lets the other stream drain and the timeout clock advance.
        for _ in range(8):
            if self.eof:
                break
            try:
                chunk = os.read(self.stream.fileno(), 64 * 1024)
            except BlockingIOError:
                break
            if not chunk:
                self.eof = True
                break
            active = True
            self.observed += len(chunk)
            available = self.limit - len(self.data)
            self.data.extend(chunk[:available])
            self.truncated |= len(chunk) > available
        return active

    def text(self) -> tuple[str, bool]:
        try:
            return self.data.decode("utf-8"), False
        except UnicodeDecodeError:
            return self.data.decode("utf-8", errors="replace"), True


def _executable(command: str, cwd: Path, environment: Mapping[str, str]) -> str:
    path = Path(command)
    if path.is_absolute() or path.parent != Path(".") or "/" in command or "\\" in command:
        selected = path if path.is_absolute() else cwd / path
    elif os.name == "nt":
        # Windows' implicit executable search may consult the parent's cwd/PATH.
        # Resolve ourselves using only the controlled, absolute search directories.
        names = [command] if path.suffix else [command + ".exe", command + ".com"]
        selected = next(
            (
                Path(folder) / name
                for folder in environment.get("PATH", "").split(os.pathsep)
                if Path(folder).is_absolute()
                for name in names
                if (Path(folder) / name).is_file()
            ),
            Path(""),
        )
    else:
        match = shutil.which(command, path=environment.get("PATH", ""))
        if match is None:
            raise FileNotFoundError("executable not found in controlled PATH")
        selected = Path(match)
    if not selected.is_file():
        raise FileNotFoundError("executable is not an existing file")
    if os.name == "nt" and selected.suffix.casefold() not in {".exe", ".com"}:
        raise OSError("Windows execution accepts native .exe/.com programs, not batch files")
    return str(selected.absolute())


class ProcessRunner:
    def __init__(self, options: ProcessOptions | None = None) -> None:
        self.options = options or ProcessOptions()

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        observer: Observer | None = None,
    ) -> ExecutionResult:
        arguments = TypeAdapter(Command).validate_python(command)
        timeout = TypeAdapter(PositiveSeconds).validate_python(timeout_seconds)
        observations = observer or NullObserver()
        started = time.perf_counter()
        process: subprocess.Popen[bytes] | None = None
        tree: ProcessTree | None = None
        try:
            executable = _executable(arguments[0], cwd, environment)
            tree = ProcessTree()
            process = subprocess.Popen(
                arguments,
                executable=executable,
                cwd=cwd,
                env=dict(environment),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                close_fds=True,
                start_new_session=os.name != "nt",
                creationflags=tree.creation_flags,
            )
            tree.attach(process)
            observations.emit(
                EventType.PROCESS_STARTED,
                ProcessStartedPayload(
                    executable_name=executable.replace("\\", "/").rsplit("/", 1)[-1],
                    arguments_omitted=len(arguments) - 1,
                ),
            )
            assert process.stdout is not None and process.stderr is not None
            stdout = _Capture(process.stdout, self.options.max_stdout_bytes)
            stderr = _Capture(process.stderr, self.options.max_stderr_bytes)
        except BaseException as error:
            # Setup also owns cleanup during cancellation, including a still-suspended child.
            try:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    if tree is not None:
                        tree.terminate(process, self.options.cleanup_timeout_seconds)
                    else:
                        process.wait(timeout=self.options.cleanup_timeout_seconds)
            except (OSError, subprocess.TimeoutExpired) as cleanup_error:
                raise ProcessError(
                    f"process setup cleanup failed: {cleanup_error}",
                    arguments,
                    (time.perf_counter() - started) * 1000,
                ) from error
            finally:
                if tree is not None:
                    tree.close()
                if process is not None:
                    for stream in (process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()
            if not isinstance(error, (OSError, ValueError)):
                raise
            raise ProcessLaunchError(
                f"command launch/setup failed: {error}",
                arguments,
                (time.perf_counter() - started) * 1000,
            ) from error
        timed_out = False
        cleaned = False
        try:
            while process.poll() is None:
                active = stdout.drain() | stderr.drain()
                if time.perf_counter() - started >= timeout:
                    timed_out = True
                    observations.emit(EventType.PROCESS_TIMED_OUT, EmptyPayload())
                    break
                if not active:
                    time.sleep(0.005)
            # Clean background descendants after both normal exit and timeout.
            tree.terminate(process, self.options.cleanup_timeout_seconds)
            cleaned = True
            drain_deadline = time.perf_counter() + self.options.cleanup_timeout_seconds
            while not (stdout.eof and stderr.eof):
                active = stdout.drain() | stderr.drain()
                if time.perf_counter() >= drain_deadline:
                    stdout.truncated |= not stdout.eof
                    stderr.truncated |= not stderr.eof
                    break
                if not active:
                    time.sleep(0.005)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ProcessError(
                f"command capture/cleanup failed: {error}",
                arguments,
                (time.perf_counter() - started) * 1000,
            ) from error
        finally:
            # Also owns cleanup on interruption; never leave a normal in-group child running.
            try:
                if not cleaned:
                    tree.terminate(process, self.options.cleanup_timeout_seconds)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ProcessError(
                    f"command cleanup failed: {error}",
                    arguments,
                    (time.perf_counter() - started) * 1000,
                ) from error
            finally:
                tree.close()
                process.stdout.close()
                process.stderr.close()
        out, out_errors = stdout.text()
        err, err_errors = stderr.text()
        result = ExecutionResult(
            command=arguments,
            exit_code=process.returncode,
            stdout=out,
            stderr=err,
            duration_ms=(time.perf_counter() - started) * 1000,
            timed_out=timed_out,
            stdout_truncated=stdout.truncated,
            stderr_truncated=stderr.truncated,
            stdout_decode_errors=out_errors,
            stderr_decode_errors=err_errors,
            stdout_bytes_observed=stdout.observed,
            stderr_bytes_observed=stderr.observed,
        )
        observations.emit(
            EventType.PROCESS_COMPLETED,
            ProcessCompletedPayload(
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
                timed_out=result.timed_out,
                stdout_bytes_observed=stdout.observed,
                stderr_bytes_observed=stderr.observed,
                stdout_truncated=result.stdout_truncated,
                stderr_truncated=result.stderr_truncated,
            ),
        )
        return result
