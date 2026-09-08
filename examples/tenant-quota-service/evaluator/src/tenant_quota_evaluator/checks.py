"""Operator-owned unittest cases. Candidate code is imported only inside tests."""

import unittest
from typing import Any


class QuotaContract(unittest.TestCase):
    def service(self, default: int = 3, overrides: dict[str, int] | None = None) -> Any:
        from job_service import JobService, ServiceConfig

        return JobService(
            config=ServiceConfig(
                default_active_job_limit=default,
                tenant_active_job_limits={} if overrides is None else overrides,
            )
        )

    def rejected(self, service: Any, tenant: str, limit: int, active: int) -> None:
        before = service.list_jobs()
        try:
            service.submit_job(tenant, {"attempt": "rejected"})
        except Exception as error:
            from job_service.errors import QuotaExceededError

            self.assertIsInstance(error, QuotaExceededError)
            self.assertEqual(
                (error.tenant_id, error.limit, error.active_count), (tenant, limit, active)
            )
            self.assertIn(tenant, str(error))
            self.assertIn(str(limit), str(error))
        else:
            self.fail("Submission at the active limit was accepted")
        self.assertEqual(
            service.list_jobs(), before, "Rejected submission changed repository state"
        )

    def test_default_constructor_enforces_three(self) -> None:
        from job_service import JobService

        service = JobService()
        for _ in range(3):
            service.submit_job("standard", {})
        self.rejected(service, "standard", 3, 3)

    def test_configured_default_and_exact_boundary(self) -> None:
        for limit in (1, 2, 5):
            with self.subTest(limit=limit):
                service = self.service(limit)
                for _ in range(limit):
                    service.submit_job("standard", {})
                self.rejected(service, "standard", limit, limit)

    def test_overrides_replace_default_in_both_directions(self) -> None:
        service = self.service(2, {"larger": 4, "smaller": 1})
        for tenant, limit in (("larger", 4), ("smaller", 1), ("ordinary", 2)):
            for _ in range(limit):
                service.submit_job(tenant, {})
            self.rejected(service, tenant, limit, limit)

    def test_zero_default_and_zero_override(self) -> None:
        service = self.service(0, {"enabled": 1})
        self.rejected(service, "disabled", 0, 0)
        service.submit_job("enabled", {})
        self.rejected(self.service(3, {"paused": 0}), "paused", 0, 0)

    def test_pending_and_running_both_remain_active(self) -> None:
        from job_service import JobStatus

        service = self.service(2)
        first = service.submit_job("alpha", {})
        service.submit_job("alpha", {})
        service.set_status(first.id, JobStatus.RUNNING)
        self.rejected(service, "alpha", 2, 2)

    def test_each_terminal_status_releases_capacity_immediately(self) -> None:
        from job_service import JobStatus

        for terminal in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED):
            with self.subTest(terminal=terminal):
                service = self.service(1)
                for _ in range(3):
                    job = service.submit_job("alpha", {})
                    service.set_status(job.id, JobStatus.RUNNING)
                    self.rejected(service, "alpha", 1, 1)
                    service.set_status(job.id, terminal)
                self.assertEqual(len(service.list_jobs("alpha")), 3)

    def test_pending_cancellation_frees_one_slot_without_reopening(self) -> None:
        from job_service import JobStatus
        from job_service.errors import InvalidTransitionError

        service = self.service(2)
        first = service.submit_job("alpha", {})
        service.submit_job("alpha", {})
        service.set_status(first.id, JobStatus.CANCELLED)
        service.set_status(first.id, JobStatus.CANCELLED)
        service.submit_job("alpha", {})
        self.rejected(service, "alpha", 2, 2)
        with self.assertRaises(InvalidTransitionError):
            service.set_status(first.id, JobStatus.PENDING)

    def test_tenants_are_independent(self) -> None:
        service = self.service(1)
        for tenant in ("alpha", "beta", "Alpha", " alpha "):
            service.submit_job(tenant, {})
            self.rejected(service, tenant, 1, 1)
        self.assertEqual(len(service.list_jobs()), 4)

    def test_repeated_rejections_do_not_consume_ids_or_persist(self) -> None:
        from job_service import JobStatus

        service = self.service(1)
        first = service.submit_job("alpha", {"kind": "original"})
        for _ in range(3):
            self.rejected(service, "alpha", 1, 1)
        self.assertEqual(service.get_job(first.id).payload, {"kind": "original"})
        service.set_status(first.id, JobStatus.CANCELLED)
        self.assertEqual(service.submit_job("alpha", {}).id, "job-2")

    def test_invalid_limits_fail_at_construction(self) -> None:
        from job_service import ServiceConfig

        for invalid in (-1, -20, True, 1.5, "2"):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    ServiceConfig(default_active_job_limit=invalid)
                with self.assertRaises(ValueError):
                    ServiceConfig(tenant_active_job_limits={"unused": invalid})

    def test_configuration_is_a_snapshot(self) -> None:
        from job_service import JobService, ServiceConfig

        limits = {"alpha": 1}
        config = ServiceConfig(default_active_job_limit=2, tenant_active_job_limits=limits)
        limits["alpha"] = 100
        service = JobService(config=config)
        service.submit_job("alpha", {})
        self.rejected(service, "alpha", 1, 1)
        with self.assertRaises(ValueError):
            ServiceConfig(tenant_active_job_limits={" ": 1})

    def test_existing_repository_state_and_sequential_shared_services(self) -> None:
        from job_service import InMemoryJobRepository, JobService, JobStatus, ServiceConfig

        repository = InMemoryJobRepository()
        seeded = repository.create("alpha", {}, id_prefix="job")
        config = ServiceConfig(default_active_job_limit=1)
        first, second = JobService(repository, config), JobService(repository, config)
        self.rejected(first, "alpha", 1, 1)
        second.set_status(seeded.id, JobStatus.CANCELLED)
        accepted = first.submit_job("alpha", {})
        self.assertEqual(second.get_job(accepted.id), accepted)
        self.rejected(second, "alpha", 1, 1)

    def test_existing_api_scheduling_order_and_snapshots(self) -> None:
        from job_service import JobService, JobStatus, ServiceConfig
        from job_service.errors import InvalidTransitionError, JobNotFoundError

        service = JobService(config=ServiceConfig(id_prefix="batch"))
        payload = {"kind": "resize"}
        first = service.submit_job("alpha", payload)
        second = service.submit_job("beta", {})
        payload["kind"] = "changed"
        self.assertEqual((first.id, second.id), ("batch-1", "batch-2"))
        self.assertEqual(first.payload, {"kind": "resize"})
        self.assertEqual(service.list_jobs(), (first, second))
        self.assertEqual(service.list_jobs("alpha"), (first,))
        self.assertEqual(service.list_jobs("missing"), ())
        with self.assertRaises(InvalidTransitionError):
            service.set_status(first.id, JobStatus.SUCCEEDED)
        running = service.set_status(first.id, JobStatus.RUNNING)
        self.assertEqual(first.status, JobStatus.PENDING)
        self.assertEqual(running.status, JobStatus.RUNNING)
        self.assertEqual(service.get_job(first.id), running)
        with self.assertRaises(JobNotFoundError) as missing:
            service.get_job("missing")
        self.assertEqual(missing.exception.job_id, "missing")

    def test_invalid_inputs_still_fail_before_quota_check(self) -> None:
        service = self.service(0)
        with self.assertRaises(ValueError):
            service.submit_job(" ", {})
        with self.assertRaises(ValueError):
            service.submit_job("alpha", {"not": 42})
        self.assertEqual(service.list_jobs(), ())
