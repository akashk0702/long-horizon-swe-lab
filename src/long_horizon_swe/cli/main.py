"""Configuration validation and measured behavioral verification."""

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from long_horizon_swe.application.verification import verify_manifest
from long_horizon_swe.config.loader import load_task
from long_horizon_swe.config.workspace import resolve_workspace
from long_horizon_swe.core.exceptions import LabError
from long_horizon_swe.core.state import TaskState
from long_horizon_swe.evaluation.verifier import BehavioralVerifier
from long_horizon_swe.execution.options import ProcessOptions, WorkspaceOptions
from long_horizon_swe.execution.process import ProcessRunner
from long_horizon_swe.execution.runner import TaskRunner
from long_horizon_swe.tracking.errors import TraceError
from long_horizon_swe.tracking.reader import read_trace
from long_horizon_swe.tracking.replay import render_json, render_timeline


def nonnegative_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a nonnegative integer") from error
    if number < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="long-swe",
        description="Validate task contracts or execute an operator-trusted verifier in a copy.",
    )
    parser.add_argument("--version", action="version", version=version("long-horizon-swe-lab"))
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a manifest and its workspace paths")
    validate.add_argument("task_file", type=Path, help="UTF-8 YAML task manifest")
    verify = commands.add_parser("verify", help="run the JSON verifier in a disposable workspace")
    verify.add_argument("task_file", type=Path)
    verify.add_argument(
        "--retain-on-failure", action="store_true", help="retain failed run directories"
    )
    verify.add_argument("--temp-parent", type=Path, help="existing directory outside the source")
    verify.add_argument("--max-stdout-bytes", type=nonnegative_integer, default=1024 * 1024)
    verify.add_argument("--max-stderr-bytes", type=nonnegative_integer, default=256 * 1024)
    verify.add_argument("--output-root", type=Path, help="artifact root outside the task directory")
    replay = commands.add_parser("replay", help="read stored evidence without executing commands")
    replay.add_argument("trace_file", type=Path)
    replay.add_argument(
        "--json", action="store_true", help="emit validated event records as a JSON array"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "replay":
            trace = read_trace(args.trace_file)
            print(render_json(trace) if args.json else render_timeline(trace))
            return 0
        if args.command == "verify":
            runner = TaskRunner(
                BehavioralVerifier(
                    ProcessRunner(
                        ProcessOptions(
                            max_stdout_bytes=args.max_stdout_bytes,
                            max_stderr_bytes=args.max_stderr_bytes,
                        )
                    )
                ),
                WorkspaceOptions(
                    temp_parent=args.temp_parent, retain_on_failure=args.retain_on_failure
                ),
            )
            run = verify_manifest(args.task_file, output_root=args.output_root, runner=runner)
            print(run.result.model_dump_json())
            print(f"Artifacts: {run.directory}", file=sys.stderr)
            return 0 if run.result.status == TaskState.COMPLETED else 1
        task = load_task(args.task_file)
        workspace = resolve_workspace(task, args.task_file)
    except TraceError as error:
        print(
            json.dumps(
                {
                    "error": type(error).__name__,
                    "message": str(error),
                    "line_number": error.line_number,
                }
            ),
            file=sys.stderr,
        )
        return 2
    except LabError as error:
        print(
            json.dumps({"valid": False, "error": type(error).__name__, "message": str(error)}),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "valid": True,
                "task_id": task.id,
                "schema_version": task.schema_version,
                "workspace": str(workspace),
            },
            sort_keys=True,
        )
    )
    return 0
