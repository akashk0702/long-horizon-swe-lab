"""Task-quality checks; mutation operators create temporary faulty copies only."""

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

TASK = Path(__file__).resolve().parents[1] / "examples" / "tenant-quota-service"


def snapshot() -> dict[str, bytes]:
    return {p.relative_to(TASK).as_posix(): p.read_bytes() for p in TASK.rglob("*") if p.is_file()}


def reference(tmp_path: Path) -> Path:
    namespace = runpy.run_path(str(TASK / "prepare_task.py"), run_name="quota_reference_setup")
    return namespace["prepare"](tmp_path / "reference", apply_reference=True)


def developer_checks(source: Path) -> None:
    with prepare_workspace(source) as workspace:
        environment = build_environment(workspace)
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        outcome = ProcessRunner().run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=workspace.cwd,
            environment=environment,
            timeout_seconds=30,
        )
        assert outcome.succeeded, outcome.stdout + outcome.stderr
        types = ProcessRunner().run(
            [sys.executable, "-m", "mypy", "--strict", "src"],
            cwd=workspace.cwd,
            environment=environment,
            timeout_seconds=30,
        )
        assert types.succeeded, types.stdout + types.stderr


def verify(manifest: Path, output: Path) -> VerificationRun:
    run = verify_manifest(manifest, output_root=output)
    assert run.result.verification is not None
    assert run.result.executions, run.result.failure_reason
    assert not run.result.executions[0].timed_out
    assert not run.result.executions[0].stdout_truncated
    return run


def test_start_is_functional_but_feature_missing_and_source_unchanged(tmp_path: Path) -> None:
    before = snapshot()
    developer_checks(TASK / "start")
    run = verify(TASK / "task.yaml", tmp_path / "runs")
    verdict = run.result.verification
    assert verdict.passed is False
    assert (verdict.tests_passed, verdict.tests_failed, verdict.exit_code) == (1, 13, 1)
    assert "Failed behavioral case: test_default_constructor_enforces_three" in verdict.details
    assert read_trace(run.directory / "trace.jsonl").events[-1].event_type == EventType.RUN_FAILED
    assert snapshot() == before
    assert not (TASK / "start" / "evaluator").exists()


def test_reference_preserves_tests_passes_repeatedly_and_does_not_change_fixtures(
    tmp_path: Path,
) -> None:
    before = snapshot()
    manifest = reference(tmp_path)
    developer_checks(manifest.parent / "start")
    observed = []
    run_ids = set()
    for _ in range(3):
        run = verify(manifest, tmp_path / "runs")
        verdict = run.result.verification
        observed.append(
            (verdict.passed, verdict.tests_passed, verdict.tests_failed, verdict.exit_code)
        )
        run_ids.add(run.run_id)
        assert (
            read_trace(run.directory / "trace.jsonl").events[-1].event_type
            == EventType.RUN_COMPLETED
        )
    assert observed == [(True, 14, 0, 0)] * 3
    assert len(run_ids) == 3
    assert snapshot() == before


def replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, "Mutation no longer identifies exactly one intended operation"
    return source.replace(old, new, 1)


def weaken(path: Path, mutation: str) -> None:
    source = path.read_text(encoding="utf-8")
    if mutation == "count_all_jobs":
        source = replace_once(
            source, "job.status in {JobStatus.PENDING, JobStatus.RUNNING}", "True"
        )
    elif mutation == "global_quota":
        source = replace_once(
            source,
            "for job in self.repository.list(tenant_id)",
            "for job in self.repository.list()",
        )
    elif mutation == "off_by_one":
        source = replace_once(source, "if active_count >= limit:", "if active_count > limit:")
    elif mutation == "persist_before_rejection":
        creation = "self.repository.create(tenant_id, payload, id_prefix=self.config.id_prefix)"
        source = replace_once(source, "return " + creation, "return created")
        source = replace_once(
            source,
            "        if active_count >= limit:",
            "        created = " + creation + "\n        if active_count >= limit:",
        )
    elif mutation == "ignore_override":
        source = replace_once(
            source,
            "limit = self.config.tenant_active_job_limits.get(\n"
            "            tenant_id, self.config.default_active_job_limit\n        )",
            "limit = self.config.default_active_job_limit",
        )
    else:
        raise AssertionError("unknown development mutation")
    path.write_text(source, encoding="utf-8")


@pytest.mark.parametrize(
    ("mutation", "expected_case"),
    [
        ("count_all_jobs", "test_each_terminal_status_releases_capacity_immediately"),
        ("global_quota", "test_tenants_are_independent"),
        ("off_by_one", "test_configured_default_and_exact_boundary"),
        ("persist_before_rejection", "test_repeated_rejections_do_not_consume_ids_or_persist"),
        ("ignore_override", "test_overrides_replace_default_in_both_directions"),
    ],
)
def test_evaluator_rejects_weak_implementation_for_behavioral_reason(
    tmp_path: Path, mutation: str, expected_case: str
) -> None:
    before = snapshot()
    manifest = reference(tmp_path)
    weaken(manifest.parent / "start/src/job_service/service.py", mutation)
    run = verify(manifest, tmp_path / "runs")
    verdict = run.result.verification
    assert not verdict.passed
    assert verdict.tests_failed > 0
    assert "Failed behavioral case: " + expected_case in verdict.details
    assert verdict.tests_passed + verdict.tests_failed == 14
    assert snapshot() == before


def test_candidate_reports_and_deleted_tests_cannot_replace_external_assertions(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(TASK / "start", candidate / "start")
    shutil.copyfile(TASK / "task.yaml", candidate / "task.yaml")
    fake = {
        "schema_version": "1.0",
        "passed": True,
        "tests_passed": 14,
        "tests_failed": 0,
        "details": [],
    }
    (candidate / "start" / "result.json").write_text(json.dumps(fake), encoding="utf-8")
    tests = (candidate / "start" / "tests").resolve()
    assert tests.parent == (candidate / "start").resolve()
    shutil.rmtree(tests)
    # This file must never be loaded by the installed evaluator.
    (candidate / "start" / "conftest.py").write_text(
        "raise RuntimeError('candidate hook loaded')", encoding="utf-8"
    )
    module = candidate / "start/src/job_service/__init__.py"
    with module.open("a", encoding="utf-8") as stream:
        stream.write("\nprint(" + repr(json.dumps(fake)) + ")\n")
    run = verify(candidate / "task.yaml", tmp_path / "runs")
    assert (run.result.verification.tests_passed, run.result.verification.tests_failed) == (1, 13)
    assert run.result.executions[0].stderr == ""


def test_reference_preparation_refuses_to_overwrite_or_write_inside_fixture(tmp_path: Path) -> None:
    before = snapshot()
    manifest = reference(tmp_path)
    with pytest.raises(FileExistsError):
        reference(tmp_path)
    namespace = runpy.run_path(str(TASK / "prepare_task.py"), run_name="quota_reference_setup")
    with pytest.raises(ValueError, match="outside"):
        namespace["prepare"](TASK / "forbidden-output")
    assert manifest.is_file()
    assert snapshot() == before


def test_persistent_evaluator_modification_is_detected_in_disposable_installation(
    tmp_path: Path,
) -> None:
    import yaml

    manifest = reference(tmp_path)
    trusted = tmp_path / "operator"
    shutil.copytree(
        TASK / "evaluator/src/tenant_quota_evaluator", trusted / "tenant_quota_evaluator"
    )
    command = (
        "import sys,runpy; sys.path.insert(0, " + repr(str(trusted)) + "); "
        "runpy.run_module('tenant_quota_evaluator', run_name='__main__')"
    )
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["verification_command"] = [sys.executable, "-I", "-c", command]
    manifest.write_text(yaml.safe_dump(data), encoding="utf-8")
    candidate = manifest.parent / "start/src/job_service/__init__.py"
    with candidate.open("a", encoding="utf-8") as stream:
        stream.write(
            "\nfrom pathlib import Path\nimport tenant_quota_evaluator\n"
            "Path(tenant_quota_evaluator.__file__).with_name('checks.py').write_text("
            "'# synthetic integrity probe\\n', encoding='utf-8')\n"
        )
    run = verify(manifest, tmp_path / "runs")
    assert not run.result.verification.passed
    assert run.result.verification.tests_passed is None
    assert run.result.executions[0].exit_code == 2
    assert "integrity" in run.result.executions[0].stderr
