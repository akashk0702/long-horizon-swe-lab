"""Ownership and teardown of a command's process group or Windows Job Object."""

import os
import signal
import subprocess
import sys
from contextlib import suppress

from long_horizon_swe.execution._windows import WindowsJob


class ProcessTree:
    def __init__(self) -> None:
        self.job = WindowsJob() if os.name == "nt" else None

    @property
    def creation_flags(self) -> int:
        # CREATE_SUSPENDED | CREATE_NEW_PROCESS_GROUP on Windows.
        return 0x00000004 | 0x00000200 if self.job is not None else 0

    def attach(self, process: subprocess.Popen[bytes]) -> None:
        if self.job is not None:
            self.job.attach_and_resume(process.pid)

    def terminate(self, process: subprocess.Popen[bytes], timeout: float) -> None:
        if self.job is not None:
            self.job.terminate(timeout)
        elif sys.platform != "win32":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=timeout)

    def close(self) -> None:
        if self.job is not None:
            self.job.close()
