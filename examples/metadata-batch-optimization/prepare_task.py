"""Copy this task into a new external directory, optionally applying its reference overlay."""

import argparse
import shutil
from pathlib import Path


def prepare(destination: Path, *, apply_reference: bool = False) -> Path:
    task = Path(__file__).resolve().parent
    destination = destination.resolve()
    if destination.is_relative_to(task):
        raise ValueError("destination must be outside the original task directory")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(task / "start", destination / "start")
    if apply_reference:
        for source in (task / "reference_solution" / "src").rglob("*.py"):
            relative = source.relative_to(task / "reference_solution")
            target = destination / "start" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    shutil.copyfile(task / "task.yaml", destination / "task.yaml")
    return destination / "task.yaml"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new directory outside this task")
    parser.add_argument("--reference", action="store_true", help="apply the reference overlay")
    args = parser.parse_args()
    print(prepare(args.destination, apply_reference=args.reference))
