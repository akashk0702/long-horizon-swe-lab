import pytest
from job_service.errors import JobNotFoundError
from job_service.models import JobStatus
from job_service.repository import InMemoryJobRepository


def test_repository_keeps_insertion_order_and_tenant_filter() -> None:
    repo = InMemoryJobRepository()
    first = repo.create("alpha", {"kind": "email"}, id_prefix="job")
    second = repo.create("beta", {}, id_prefix="job")
    third = repo.create("alpha", {}, id_prefix="job")
    assert repo.list() == (first, second, third)
    assert repo.list("alpha") == (first, third)
    assert repo.list("absent") == ()
    assert (first.id, second.id, third.id) == ("job-1", "job-2", "job-3")


def test_snapshots_and_payloads_do_not_mutate_storage() -> None:
    repo = InMemoryJobRepository()
    payload = {"kind": "email"}
    pending = repo.create("alpha", payload, id_prefix="job")
    payload["kind"] = "changed"
    running = repo.update_status(pending.id, JobStatus.RUNNING)
    assert pending.status == JobStatus.PENDING
    assert running.status == JobStatus.RUNNING
    assert repo.get(pending.id).payload == {"kind": "email"}
    with pytest.raises(TypeError):
        running.payload["kind"] = "changed"  # type: ignore[index]


def test_missing_job_is_a_domain_error() -> None:
    with pytest.raises(JobNotFoundError) as error:
        InMemoryJobRepository().get("missing")
    assert error.value.job_id == "missing"


def test_repositories_have_independent_state() -> None:
    first, second = InMemoryJobRepository(), InMemoryJobRepository()
    first.create("alpha", {}, id_prefix="job")
    assert second.list() == ()
    assert second.create("alpha", {}, id_prefix="job").id == "job-1"
