"""Measure task solvability and reject incomplete optimizations using external assertions."""

import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

from long_horizon_swe.application.verification import VerificationRun, verify_manifest
from long_horizon_swe.execution.environment import build_environment
from long_horizon_swe.execution.process import ProcessRunner
from long_horizon_swe.execution.workspace import prepare_workspace
from long_horizon_swe.tracking.event import EventType
from long_horizon_swe.tracking.reader import read_trace

TASK = Path(__file__).resolve().parents[1] / "examples/metadata-batch-optimization"


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def prepare(destination: Path, *, reference: bool = False) -> Path:
    module = runpy.run_path(str(TASK / "prepare_task.py"), run_name="metadata_task_setup")
    return module["prepare"](destination, apply_reference=reference)


def developer_checks(source: Path) -> None:
    with prepare_workspace(source) as workspace:
        environment = build_environment(workspace)
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        for command in (
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            [sys.executable, "-m", "mypy", "--strict", "src"],
        ):
            result = ProcessRunner().run(
                command, cwd=workspace.cwd, environment=environment, timeout_seconds=30
            )
            assert result.succeeded, result.stdout + result.stderr


def verify(manifest: Path, output: Path) -> VerificationRun:
    before = snapshot(manifest.parent)
    run = verify_manifest(manifest, output_root=output)
    assert run.result.verification is not None
    assert len(run.result.executions) == 1, run.result.failure_reason
    assert not run.result.executions[0].timed_out
    assert not run.result.executions[0].stdout_truncated
    assert snapshot(manifest.parent) == before
    return run


def test_baseline_is_functionally_correct_but_repeats_work(tmp_path: Path) -> None:
    before = snapshot(TASK)
    developer_checks(TASK / "start")
    run = verify(TASK / "task.yaml", tmp_path / "runs")
    verdict = run.result.verification
    assert (verdict.passed, verdict.tests_passed, verdict.tests_failed, verdict.exit_code) == (
        False,
        16,
        3,
        1,
    )
    assert set(verdict.details) == {
        "Failed behavioral case: test_efficiency_retrieval_per_distinct_profile",
        "Failed behavioral case: test_efficiency_decode_per_distinct_profile",
        "Failed behavioral case: test_efficiency_prefix_before_error",
    }
    assert read_trace(run.directory / "trace.jsonl").events[-1].event_type == EventType.RUN_FAILED
    assert snapshot(TASK) == before


def test_reference_preserves_behavior_and_repeats_verdict(tmp_path: Path) -> None:
    before = snapshot(TASK)
    manifest = prepare(tmp_path / "reference", reference=True)
    developer_checks(manifest.parent / "start")
    identifiers = set()
    for _ in range(3):
        run = verify(manifest, tmp_path / "runs")
        verdict = run.result.verification
        assert (verdict.passed, verdict.tests_passed, verdict.tests_failed, verdict.exit_code) == (
            True,
            19,
            0,
            0,
        )
        identifiers.add(run.run_id)
        assert (
            read_trace(run.directory / "trace.jsonl").events[-1].event_type
            == EventType.RUN_COMPLETED
        )
    assert len(identifiers) == 3
    assert snapshot(TASK) == before


def replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, "Development edit must select exactly one intended operation"
    return text.replace(old, new, 1)


def alternative_processor() -> str:
    baseline = (TASK / "start/src/metadata_pipeline/processor.py").read_text(encoding="utf-8")
    prefix = baseline.split("    def enrich(", 1)[0]
    # Preflight in input order preserves the first error before materializing any outputs.
    return (
        prefix
        + """    def enrich(self, records: Sequence[InputRecord]) -> list[EnrichedRecord]:
        resolved: dict[str, MetadataProfile] = {}
        for record in records:
            if record.profile_id not in resolved:
                value = self._repository.get_encoded(record.profile_id)
                resolved[record.profile_id] = self._decoder.decode(record.profile_id, value)
            validate_record(record, resolved[record.profile_id])
        return [render_record(record, resolved[record.profile_id]) for record in records]
"""
    )


def test_separate_preflight_and_materialization_is_accepted(tmp_path: Path) -> None:
    before = snapshot(TASK)
    manifest = prepare(tmp_path / "alternative")
    (manifest.parent / "start/src/metadata_pipeline/processor.py").write_text(
        alternative_processor(), encoding="utf-8"
    )
    developer_checks(manifest.parent / "start")
    verdict = verify(manifest, tmp_path / "runs").result.verification
    assert (verdict.passed, verdict.tests_passed, verdict.tests_failed) == (True, 19, 0)
    assert snapshot(TASK) == before


def weaken(source: Path, variant: str) -> None:
    path = source / "src/metadata_pipeline/processor.py"
    text = path.read_text(encoding="utf-8")
    if variant == "persistent_cache":
        text = replace_once(
            text,
            "        self._decoder = decoder",
            "        self._decoder = decoder\n"
            "        self._profiles: dict[str, MetadataProfile] = {}",
        )
        text = replace_once(
            text,
            "        profiles: dict[str, MetadataProfile] = {}",
            "        profiles = self._profiles",
        )
    elif variant == "retrieve_once_decode_repeatedly":
        text = replace_once(
            text,
            "        profiles: dict[str, MetadataProfile] = {}",
            "        encoded_profiles: dict[str, str] = {}",
        )
        begin = text.index("            if record.profile_id not in profiles:")
        end = text.index("            validate_record(record, profile)", begin)
        text = (
            text[:begin]
            + """            if record.profile_id not in encoded_profiles:
                value = self._repository.get_encoded(record.profile_id)
                encoded_profiles[record.profile_id] = value
            profile = self._decoder.decode(record.profile_id, encoded_profiles[record.profile_id])
"""
            + text[end:]
        )
    elif variant == "decode_once_retrieve_repeatedly":
        text = replace_once(
            text,
            "            if record.profile_id not in profiles:\n"
            "                encoded = self._repository.get_encoded(record.profile_id)",
            "            encoded = self._repository.get_encoded(record.profile_id)\n"
            "            if record.profile_id not in profiles:",
        )
    elif variant == "record_id_key":
        text = text.replace("profiles[record.profile_id]", "profiles[record.record_id]")
        text = replace_once(
            text, "if record.profile_id not in profiles:", "if record.record_id not in profiles:"
        )
    elif variant == "grouped_order":
        text = replace_once(
            text,
            "        for record in records:",
            "        for record in sorted(records, key=lambda row: row.profile_id):",
        )
    elif variant == "one_profile_for_every_record":
        text = text.replace("profiles[record.profile_id]", 'profiles["one"]')
        text = replace_once(
            text, "if record.profile_id not in profiles:", 'if "one" not in profiles:'
        )
    else:
        raise AssertionError("unknown development variant")
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("variant", "rejecting_case"),
    [
        ("persistent_cache", "test_functional_freshness_between_calls"),
        ("retrieve_once_decode_repeatedly", "test_efficiency_decode_per_distinct_profile"),
        ("decode_once_retrieve_repeatedly", "test_efficiency_retrieval_per_distinct_profile"),
        ("record_id_key", "test_efficiency_retrieval_per_distinct_profile"),
        ("grouped_order", "test_functional_interleaved_order"),
        ("one_profile_for_every_record", "test_functional_interleaved_order"),
    ],
)
def test_incorrect_optimization_is_rejected(
    tmp_path: Path, variant: str, rejecting_case: str
) -> None:
    before = snapshot(TASK)
    manifest = prepare(tmp_path / "variant", reference=True)
    weaken(manifest.parent / "start", variant)
    verdict = verify(manifest, tmp_path / "runs").result.verification
    assert verdict.passed is False
    assert verdict.exit_code == 1
    assert verdict.tests_failed > 0
    assert verdict.tests_passed + verdict.tests_failed == 19
    assert "Failed behavioral case: " + rejecting_case in verdict.details
    assert snapshot(TASK) == before


def test_benchmark_measures_work_and_validated_timing_without_speed_gate(tmp_path: Path) -> None:
    before = snapshot(TASK)
    with prepare_workspace(TASK / "start") as workspace:
        result = ProcessRunner().run(
            [
                sys.executable,
                "-I",
                str(TASK / "benchmark/run_benchmark.py"),
                "--records",
                "1000",
                "--profiles",
                "8",
                "--repetitions",
                "3",
                "--warmups",
                "1",
                "--json",
            ],
            cwd=workspace.cwd,
            environment=build_environment(workspace),
            timeout_seconds=60,
        )
    assert result.succeeded, result.stdout + result.stderr
    document = json.loads(result.stdout)
    module = runpy.run_path(
        str(TASK / "benchmark/run_benchmark.py"), run_name="metadata_measurement"
    )
    report = module["Report"].model_validate(document)
    assert report.workload.records == 1000
    assert report.workload.distinct_profiles == 8
    assert (report.baseline.repository_get_count, report.baseline.decoder_call_count) == (
        1000,
        1000,
    )
    assert (report.reference.repository_get_count, report.reference.decoder_call_count) == (8, 8)
    assert len(report.baseline.durations_ms) == len(report.reference.durations_ms) == 3
    (tmp_path / "measurement.json").write_text(result.stdout, encoding="utf-8")
    document["speedup"] += 1
    with pytest.raises(ValueError, match="measured median ratio"):
        module["Report"].model_validate(document)
    assert snapshot(TASK) == before


def test_preparation_preserves_source_and_rejects_overwrite(tmp_path: Path) -> None:
    before = snapshot(TASK)
    manifest = prepare(tmp_path / "copy")
    with pytest.raises(FileExistsError):
        prepare(manifest.parent)
    with pytest.raises(ValueError, match="outside"):
        prepare(TASK / "forbidden")
    assert snapshot(manifest.parent / "start") == snapshot(TASK / "start")
    assert snapshot(TASK) == before


def test_candidate_claims_and_deleted_tests_do_not_supply_verdict(tmp_path: Path) -> None:
    before = snapshot(TASK)
    manifest = prepare(tmp_path / "candidate")
    start = manifest.parent / "start"
    tests = (start / "tests").resolve()
    assert tests.parent == start.resolve()
    shutil.rmtree(tests)
    fake = json.dumps(
        {
            "schema_version": "1.0",
            "passed": True,
            "tests_passed": 19,
            "tests_failed": 0,
            "details": [],
        }
    )
    (start / "result.json").write_text(fake, encoding="utf-8")
    (start / "conftest.py").write_text(
        "raise RuntimeError('unexpected candidate hook')", encoding="utf-8"
    )
    with (start / "src/metadata_pipeline/__init__.py").open("a", encoding="utf-8") as stream:
        stream.write("\nprint(" + repr(fake) + ")\n")
    verdict = verify(manifest, tmp_path / "runs").result.verification
    assert (verdict.passed, verdict.tests_passed, verdict.tests_failed) == (False, 16, 3)
    assert snapshot(TASK) == before
