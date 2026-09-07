"""A validation-only CLI for the first project milestone."""

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from long_horizon_swe.config.loader import load_task
from long_horizon_swe.config.workspace import resolve_workspace
from long_horizon_swe.core.exceptions import LabError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="long-swe",
        description="Validate software-engineering task contracts. No commands are executed.",
    )
    parser.add_argument("--version", action="version", version=version("long-horizon-swe-lab"))
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a manifest and its workspace paths")
    validate.add_argument("task_file", type=Path, help="UTF-8 YAML task manifest")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        task = load_task(args.task_file)
        workspace = resolve_workspace(task, args.task_file)
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
