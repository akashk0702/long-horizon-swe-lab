# JSON verifier protocol version 1.0

The operator supplies a trusted command in `TaskSpec.verification_command`. The framework executes it in the copied cwd and parses its captured stdout. It does not read candidate report files, search source code, or interpret human test-runner output.

The verifier must run behavioral assertions itself, count actual outcomes, and emit one UTF-8 JSON object. Surrounding whitespace is allowed. Banners, multiple objects, duplicate keys, non-finite numbers, extra fields, and unsupported versions are rejected. Human diagnostics belong on stderr within its limit.

Illustrative message shape, not a recorded evaluation:

```json
{
  "schema_version": "1.0",
  "passed": true,
  "tests_passed": 1,
  "tests_failed": 0,
  "details": []
}
```

All five fields are required. Counts are strict nonnegative integers; booleans and numeric strings are invalid. `passed` must equal `tests_passed > 0 and tests_failed == 0`. Failure requires nonblank diagnostic strings. Zero collected tests means failure with a diagnostic.

Success additionally requires observed exit code zero, no timeout, complete stdout/stderr capture, and valid UTF-8 stdout. Failure remains failure even if the process exits zero. Nonzero exit plus a success document is a protocol error. Timing and exit codes come from the process runner, never the message.

Malformed/missing/truncated output, timeout, and launch failure produce two null test counts: evidence is not reliably observed. Launch failure has no ExecutionResult and no invented exit code; its measured duration and diagnostics remain in VerificationResult.

## Adapter boundary

VerifierAdapter separates `build_command(task)` from `parse_result(execution)`. JsonVerifierAdapter implements this protocol. BehavioralVerifier invokes the process and translates process/protocol errors into failure outcomes. Plain pytest output is not accepted; use an operator-authored test runner that emits this schema from actual assertions.

## Trust requirement

Schema validity is not proof that meaningful tests ran. The operator must own the verifier executable, assertions, manifest, and adapter. Keep verifier code outside candidate-writable paths. Do not configure a candidate self-reporting script as the trusted command. This milestone does not authenticate verifier code or detect test tampering and cannot turn an untrusted self-report into independent evidence.

Integration tests execute an operator-authored verifier against passing and failing file contents, plus invalid protocols and preexisting report files. No sample benchmark tasks are included.
