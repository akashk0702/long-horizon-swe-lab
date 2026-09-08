import pytest
from job_service import JobService, JobStatus, ServiceConfig
from job_service.errors import InvalidTransitionError, JobNotFoundError


def test_submit_get_and_list_preserve_order_and_payload() -> None:
    service = JobService(config=ServiceConfig(id_prefix="batch"))
    first = service.submit_job("alpha", {"operation": "resize"})
    second = service.submit_job("beta", {})
    assert first.id == "batch-1"
    assert first.status == JobStatus.PENDING
    assert service.get_job(first.id) == first
    assert service.list_jobs() == (first, second)
    assert service.list_jobs("alpha") == (first,)


@pytest.mark.parametrize("terminal", [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED])
def test_running_job_can_finish_without_rewriting_old_snapshots(terminal: JobStatus) -> None:
    service = JobService()
    initial = service.submit_job("alpha", {})
    service.set_status(initial.id, JobStatus.RUNNING)
    final = service.set_status(initial.id, terminal)
    assert final.status == terminal
    assert initial.status == JobStatus.PENDING
    assert service.set_status(initial.id, terminal) == final
    with pytest.raises(InvalidTransitionError):
        service.set_status(initial.id, JobStatus.RUNNING)


def test_pending_can_cancel_but_cannot_skip_running_to_succeed() -> None:
    service = JobService()
    job = service.submit_job("alpha", {})
    with pytest.raises(InvalidTransitionError):
        service.set_status(job.id, JobStatus.SUCCEEDED)
    assert service.get_job(job.id).status == JobStatus.PENDING
    assert service.set_status(job.id, JobStatus.CANCELLED).status == JobStatus.CANCELLED


def test_invalid_submission_and_status_preserve_existing_state() -> None:
    service = JobService()
    with pytest.raises(ValueError):
        service.submit_job(" ", {})
    with pytest.raises(ValueError):
        service.submit_job("alpha", {"bad": 3})  # type: ignore[dict-item]
    assert service.list_jobs() == ()
    job = service.submit_job("alpha", {})
    with pytest.raises(ValueError):
        service.set_status(job.id, "running")  # type: ignore[arg-type]
    assert service.get_job(job.id).status == JobStatus.PENDING
    with pytest.raises(JobNotFoundError):
        service.get_job("missing")


def test_invalid_prefix_fails_at_configuration_construction() -> None:
    with pytest.raises(ValueError):
        ServiceConfig(id_prefix="")
