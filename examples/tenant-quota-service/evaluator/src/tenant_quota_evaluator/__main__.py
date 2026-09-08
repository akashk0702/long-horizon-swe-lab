"""Run operator-owned assertions and emit one measured version-1.0 document."""

import contextlib
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from types import TracebackType

from tenant_quota_evaluator.checks import QuotaContract

type ExceptionInfo = tuple[type[BaseException], BaseException, TracebackType | None]


class ObservedResult(unittest.TestResult):
    """Count test methods once even when several subcases fail."""

    def __init__(self) -> None:
        super().__init__()
        self.failed_cases: set[str] = set()

    def addFailure(self, test: unittest.TestCase, err: ExceptionInfo) -> None:
        self.failed_cases.add(test.id())
        super().addFailure(test, err)

    def addError(self, test: unittest.TestCase, err: ExceptionInfo) -> None:
        self.failed_cases.add(test.id())
        super().addError(test, err)

    def addSubTest(
        self, test: unittest.TestCase, subtest: unittest.TestCase, err: ExceptionInfo | None
    ) -> None:
        if err is not None:
            self.failed_cases.add(test.id())
        super().addSubTest(test, subtest, err)


def _fingerprint() -> dict[str, str]:
    directory = Path(__file__).resolve().parent
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob("*.py")}


def main() -> int:
    candidate = (Path.cwd() / "src").resolve()
    if not candidate.is_dir() or Path(__file__).resolve().is_relative_to(Path.cwd().resolve()):
        print("Evaluator requires candidate src/ and an external installation.", file=sys.stderr)
        return 2
    # Load only this installed suite, before putting the candidate on the import path.
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(QuotaContract)
    expected = suite.countTestCases()
    before = _fingerprint()
    sys.path.insert(0, str(candidate))
    result = ObservedResult()
    # Ordinary candidate print statements cannot supply the verifier protocol.
    # Direct OS writes and malicious interpreter manipulation are outside the trust boundary.
    with (
        open(os.devnull, "w", encoding="utf-8") as sink,
        contextlib.redirect_stdout(sink),
        contextlib.redirect_stderr(sink),
    ):
        suite.run(result)
    if (
        expected == 0
        or result.testsRun != expected
        or result.skipped
        or result.expectedFailures
        or result.unexpectedSuccesses
        or _fingerprint() != before
    ):
        print(
            "Evaluator integrity or complete execution could not be established.", file=sys.stderr
        )
        return 2
    failed = len(result.failed_cases)
    document = {
        "schema_version": "1.0",
        "passed": failed == 0,
        "tests_passed": result.testsRun - failed,
        "tests_failed": failed,
        "details": [
            "Failed behavioral case: " + name.rsplit(".", 1)[-1]
            for name in sorted(result.failed_cases)
        ],
    }
    print(json.dumps(document, sort_keys=True))
    return 0 if document["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
