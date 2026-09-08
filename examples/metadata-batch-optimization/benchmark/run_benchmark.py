"""Measure identical synthetic workloads in separate, disposable process workspaces."""

import argparse
import hashlib
import importlib
import json
import platform
import shutil
import statistics
import sys
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from long_horizon_swe.execution.environment import build_environment
from long_horizon_swe.execution.process import ProcessRunner
from long_horizon_swe.execution.workspace import prepare_workspace

TASK = Path(__file__).resolve().parents[1]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Settings(StrictModel):
    records: int = Field(default=10000, ge=1, le=100000)
    distinct_profiles: int = Field(default=20, ge=1)
    repetitions: int = Field(default=7, ge=1, le=30)
    warmups: int = Field(default=2, ge=1, le=10)

    @model_validator(mode="after")
    def all_profiles_used(self) -> Self:
        if self.distinct_profiles > self.records:
            raise ValueError("distinct_profiles must not exceed records")
        return self


class Measurement(StrictModel):
    durations_ms: list[float] = Field(min_length=1)
    median_ms: float = Field(gt=0)
    repository_get_count: int = Field(ge=1)
    decoder_call_count: int = Field(ge=1)
    output_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def measured_summary(self) -> Self:
        if any(value <= 0 for value in self.durations_ms):
            raise ValueError("durations must be positive")
        if statistics.median(self.durations_ms) != self.median_ms:
            raise ValueError("median must match measured samples")
        return self


class Environment(StrictModel):
    python_version: str
    python_implementation: str
    system: str
    release: str
    version: str
    machine: str


class Report(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    environment: Environment
    workload: Settings
    labels_per_profile: Literal[32] = 32
    required_fields_per_profile: Literal[12] = 12
    baseline: Measurement
    reference: Measurement
    speedup: float = Field(gt=0)

    @model_validator(mode="after")
    def comparable_samples(self) -> Self:
        for measurement in (self.baseline, self.reference):
            if len(measurement.durations_ms) != self.workload.repetitions:
                raise ValueError("sample count must match repetitions")
        if self.baseline.output_digest != self.reference.output_digest:
            raise ValueError("implementations produced different outputs")
        if self.speedup != self.baseline.median_ms / self.reference.median_ms:
            raise ValueError("speedup must be the measured median ratio")
        return self


class EncodedRepository(Protocol):
    def get_encoded(self, profile_id: str) -> str: ...


class CountingRepository:
    def __init__(self, backing: EncodedRepository) -> None:
        self.backing = backing
        self.calls = 0

    def get_encoded(self, profile_id: str) -> str:
        self.calls += 1
        return self.backing.get_encoded(profile_id)


class CountingDecoder:
    def __init__(self, backing: Any) -> None:
        self.backing = backing
        self.calls = 0

    def decode(self, profile_id: str, encoded: str) -> Any:
        self.calls += 1
        return self.backing.decode(profile_id, encoded)


def digest(rows: list[dict[str, object]]) -> str:
    checksum = hashlib.sha256()
    for row in rows:
        checksum.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        checksum.update(b"\n")
    return checksum.hexdigest()


def worker(settings: Settings) -> Measurement:
    sys.path.insert(0, str(Path.cwd() / "src"))
    api = importlib.import_module("metadata_pipeline")
    required = [f"field-{i}" for i in range(12)]
    profiles = {
        f"p{i}": json.dumps(
            {
                "category": f"category-{i}",
                "version": i + 1,
                "labels": [f"label-{i}-{j}" for j in range(32)],
                "required_fields": required,
            }
        )
        for i in range(settings.distinct_profiles)
    }
    records = [
        api.InputRecord(
            f"r{i}",
            f"p{i % settings.distinct_profiles}",
            {
                **{field: i + j for j, field in enumerate(required)},
                "context": {"batch": "synthetic", "position": i},
            },
        )
        for i in range(settings.records)
    ]
    expected = [
        {
            "record_id": f"r{i}",
            "profile_id": f"p{i % settings.distinct_profiles}",
            "payload": {
                **{field: i + j for j, field in enumerate(required)},
                "context": {"batch": "synthetic", "position": i},
            },
            "category": f"category-{i % settings.distinct_profiles}",
            "version": i % settings.distinct_profiles + 1,
            "labels": [f"label-{i % settings.distinct_profiles}-{j}" for j in range(32)],
        }
        for i in range(settings.records)
    ]
    expected_digest = digest(expected)
    durations = []
    counts = set()
    for iteration in range(settings.warmups + settings.repetitions):
        repository = CountingRepository(api.InMemoryProfileRepository(profiles))
        decoder = CountingDecoder(api.JsonProfileDecoder())
        processor = api.BatchProcessor(repository, decoder)
        started = perf_counter_ns()
        output = processor.enrich(records)
        elapsed = perf_counter_ns() - started
        # Materialization, complete correctness comparison and hashing are outside timing.
        actual = [
            {
                "record_id": row.record_id,
                "profile_id": row.profile_id,
                "payload": row.payload,
                "category": row.category,
                "version": row.version,
                "labels": row.labels,
            }
            for row in output
        ]
        if actual != expected or digest(actual) != expected_digest:
            raise ValueError("measured output does not match the independently generated workload")
        counts.add((repository.calls, decoder.calls))
        if iteration >= settings.warmups:
            durations.append(elapsed / 1_000_000)
    if len(counts) != 1:
        raise ValueError("operation counts changed between identical runs")
    gets, decodes = counts.pop()
    return Measurement(
        durations_ms=durations,
        median_ms=statistics.median(durations),
        repository_get_count=gets,
        decoder_call_count=decodes,
        output_digest=expected_digest,
    )


def measure(settings: Settings, *, reference: bool) -> Measurement:
    with prepare_workspace(TASK / "start") as workspace:
        if reference:
            overlay = TASK / "reference_solution"
            for source in overlay.rglob("*.py"):
                shutil.copyfile(source, workspace.cwd / source.relative_to(overlay))
        execution = ProcessRunner().run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).resolve()),
                "--worker",
                settings.model_dump_json(),
            ],
            cwd=workspace.cwd,
            environment=build_environment(workspace),
            timeout_seconds=120,
        )
        if not execution.succeeded or execution.stdout_truncated:
            raise RuntimeError("measurement worker failed: " + execution.stderr)
        return Measurement.model_validate_json(execution.stdout)


def benchmark(settings: Settings) -> Report:
    baseline = measure(settings, reference=False)
    reference = measure(settings, reference=True)
    for measured, expected_count in (
        (baseline, settings.records),
        (reference, settings.distinct_profiles),
    ):
        if (measured.repository_get_count, measured.decoder_call_count) != (
            expected_count,
            expected_count,
        ):
            raise ValueError("unexpected baseline/reference operation counts")
    return Report(
        environment=Environment(
            python_version=platform.python_version(),
            python_implementation=platform.python_implementation(),
            system=platform.system(),
            release=platform.release(),
            version=platform.version(),
            machine=platform.machine(),
        ),
        workload=settings,
        baseline=baseline,
        reference=reference,
        speedup=baseline.median_ms / reference.median_ms,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=10000)
    parser.add_argument("--profiles", type=int, default=20)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--json", action="store_true", help="emit a validated measured document")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker is not None:
        print(worker(Settings.model_validate_json(args.worker)).model_dump_json())
        return 0
    report = benchmark(
        Settings(
            records=args.records,
            distinct_profiles=args.profiles,
            repetitions=args.repetitions,
            warmups=args.warmups,
        )
    )
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(
            f"{report.environment.python_implementation} {report.environment.python_version} / "
            f"{report.environment.system} {report.environment.release} {report.environment.machine}"
        )
        print(
            f"{report.workload.records} records; {report.workload.distinct_profiles} profiles; "
            f"{report.workload.warmups} warmups; {report.workload.repetitions} repetitions"
        )
        for name, measurement in (("baseline", report.baseline), ("reference", report.reference)):
            print(
                f"{name}: median={measurement.median_ms:.6f} ms; "
                f"gets={measurement.repository_get_count}; decodes={measurement.decoder_call_count}"
            )
        print(f"Measured median ratio: {report.speedup:.6f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
