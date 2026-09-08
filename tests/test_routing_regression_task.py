"""Behavioral task validation, including intentionally incomplete temporary repairs."""

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

TASK = Path(__file__).resolve().parents[1] / "examples/routing-cache-regression"


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def prepare(destination: Path, *, reference: bool = False) -> Path:
    module = runpy.run_path(str(TASK / "prepare_task.py"), run_name="routing_task_setup")
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
                command,
                cwd=workspace.cwd,
                environment=environment,
                timeout_seconds=30,
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


def test_baseline_is_functional_but_warm_resolution_is_stale(tmp_path: Path) -> None:
    before = snapshot(TASK)
    developer_checks(TASK / "start")
    run = verify(TASK / "task.yaml", tmp_path / "runs")
    verdict = run.result.verification
    assert (verdict.passed, verdict.tests_passed, verdict.tests_failed, verdict.exit_code) == (
        False,
        3,
        14,
        1,
    )
    assert "Failed behavioral case: test_cached_global_default_replacement" in verdict.details
    assert (
        "Failed behavioral case: test_complete_fallback_descent_after_cached_results"
        in verdict.details
    )
    assert read_trace(run.directory / "trace.jsonl").events[-1].event_type == EventType.RUN_FAILED
    assert snapshot(TASK) == before


def test_reference_preserves_developer_tests_and_repeats_verdict(tmp_path: Path) -> None:
    before = snapshot(TASK)
    manifest = prepare(tmp_path / "reference", reference=True)
    developer_checks(manifest.parent / "start")
    outcomes = []
    identifiers = set()
    for _ in range(3):
        run = verify(manifest, tmp_path / "runs")
        verdict = run.result.verification
        outcomes.append(
            (verdict.passed, verdict.tests_passed, verdict.tests_failed, verdict.exit_code)
        )
        identifiers.add(run.run_id)
        assert (
            read_trace(run.directory / "trace.jsonl").events[-1].event_type
            == EventType.RUN_COMPLETED
        )
    assert outcomes == [(True, 17, 0, 0)] * 3
    assert len(identifiers) == 3
    assert snapshot(TASK) == before


def replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, "Development edit no longer selects one intended operation"
    return text.replace(old, new, 1)


def conservative_cache() -> str:
    source = (TASK / "start/src/route_service/cache.py").read_text(encoding="utf-8")
    return replace_once(source, "self._entries.pop(change.key, None)", "self.clear()")


def test_different_correct_conservative_clear_is_accepted(tmp_path: Path) -> None:
    before = snapshot(TASK)
    manifest = prepare(tmp_path / "conservative", reference=True)
    (manifest.parent / "start/src/route_service/cache.py").write_text(
        conservative_cache(), encoding="utf-8"
    )
    developer_checks(manifest.parent / "start")
    run = verify(manifest, tmp_path / "runs")
    assert (
        run.result.verification.passed,
        run.result.verification.tests_passed,
        run.result.verification.tests_failed,
    ) == (True, 17, 0)
    assert snapshot(TASK) == before


def weaken(source: Path, variant: str) -> None:
    cache_path = source / "src/route_service/cache.py"
    cache = cache_path.read_text(encoding="utf-8")
    if variant == "never_invalidate":
        cache = replace_once(cache, "self._generation += 1", "pass")
    elif variant == "exact_key_only":
        cache = (TASK / "start/src/route_service/cache.py").read_text(encoding="utf-8")
    elif variant == "one_global_tenant":
        cache = conservative_cache()
        cache = replace_once(
            cache,
            "        self.clear()",
            "        if change.key.tenant_id is None:\n"
            "            first = next(iter(self._entries), None)\n"
            "            if first is not None:\n"
            "                self._entries = {key: value for key, value in self._entries.items()\n"
            "                                 if key.tenant_id != first.tenant_id}\n"
            "        else:\n            self.clear()",
        )
    elif variant == "ignore_remove_events":
        cache = replace_once(
            cache, "import RouteChange, RouteKey", "import ChangeKind, RouteChange, RouteKey"
        )
        cache = replace_once(
            cache,
            "        self._generation += 1",
            "        if change.kind == ChangeKind.SET:\n            self._generation += 1",
        )
    elif variant == "changed_precedence":
        resolver_path = source / "src/route_service/resolver.py"
        resolver = resolver_path.read_text(encoding="utf-8")
        resolver = replace_once(
            resolver,
            "            RouteKey(tenant_id=key.tenant_id),\n"
            "            RouteKey(region=key.region),",
            "            RouteKey(region=key.region),\n"
            "            RouteKey(tenant_id=key.tenant_id),",
        )
        resolver_path.write_text(resolver, encoding="utf-8")
    elif variant == "clear_on_sets_without_remove_notice":
        cache = conservative_cache()
        shutil.copyfile(
            TASK / "start/src/route_service/registry.py", source / "src/route_service/registry.py"
        )
    else:
        raise AssertionError("unknown development variant")
    cache_path.write_text(cache, encoding="utf-8")


@pytest.mark.parametrize(
    ("variant", "rejecting_case"),
    [
        ("never_invalidate", "test_cached_tenant_region_replacement"),
        ("exact_key_only", "test_cached_global_region_replacement"),
        ("one_global_tenant", "test_broad_update_refreshes_every_affected_pair"),
        ("ignore_remove_events", "test_tenant_region_removal_uses_current_fallback"),
        ("changed_precedence", "test_hierarchy_precedence"),
        (
            "clear_on_sets_without_remove_notice",
            "test_complete_fallback_descent_after_cached_results",
        ),
    ],
)
def test_incomplete_repairs_fail_behaviorally(
    tmp_path: Path, variant: str, rejecting_case: str
) -> None:
    before = snapshot(TASK)
    manifest = prepare(tmp_path / "variant", reference=True)
    weaken(manifest.parent / "start", variant)
    run = verify(manifest, tmp_path / "runs")
    verdict = run.result.verification
    assert verdict.passed is False
    assert verdict.exit_code == 1
    assert verdict.tests_failed > 0
    assert verdict.tests_passed + verdict.tests_failed == 17
    assert "Failed behavioral case: " + rejecting_case in verdict.details
    assert snapshot(TASK) == before


def test_candidate_output_and_deleted_tests_cannot_supply_acceptance(tmp_path: Path) -> None:
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
            "tests_passed": 17,
            "tests_failed": 0,
            "details": [],
        }
    )
    (start / "result.json").write_text(fake, encoding="utf-8")
    (start / "conftest.py").write_text(
        "raise RuntimeError('unexpected candidate hook')", encoding="utf-8"
    )
    with (start / "src/route_service/__init__.py").open("a", encoding="utf-8") as stream:
        stream.write("\nprint(" + repr(fake) + ")\n")
    run = verify(manifest, tmp_path / "runs")
    assert (run.result.verification.tests_passed, run.result.verification.tests_failed) == (3, 14)
    assert snapshot(TASK) == before


def test_preparation_does_not_overwrite_or_pollute_original(tmp_path: Path) -> None:
    before = snapshot(TASK)
    manifest = prepare(tmp_path / "copy")
    with pytest.raises(FileExistsError):
        prepare(manifest.parent)
    with pytest.raises(ValueError, match="outside"):
        prepare(TASK / "forbidden")
    assert snapshot(manifest.parent / "start") == snapshot(TASK / "start")
    assert snapshot(TASK) == before
