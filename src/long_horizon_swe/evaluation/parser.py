"""Parse exactly one JSON protocol document; never scrape human test output."""

import json
from typing import Literal, Self

from pydantic import StrictBool, ValidationError, model_validator

from long_horizon_swe.core.exceptions import VerifierProtocolError
from long_horizon_swe.core.types import ContractModel, NonBlank, NonNegativeInt


class VerifierDocument(ContractModel):
    schema_version: Literal["1.0"]
    passed: StrictBool
    tests_passed: NonNegativeInt
    tests_failed: NonNegativeInt
    details: tuple[NonBlank, ...]

    @model_validator(mode="after")
    def counts_agree(self) -> Self:
        if self.passed != (self.tests_passed > 0 and self.tests_failed == 0):
            raise ValueError("passed must agree with the observed test counts")
        if not self.passed and not self.details:
            raise ValueError("failed verification requires diagnostics")
        return self


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VerifierProtocolError("verifier JSON contains a duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise VerifierProtocolError("verifier JSON contains a non-finite number")


def parse_document(output: str) -> VerifierDocument:
    try:
        data = json.loads(output, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        return VerifierDocument.model_validate(data)
    except (ValueError, RecursionError, ValidationError) as error:
        raise VerifierProtocolError(
            "verifier output is not one valid version 1.0 JSON document"
        ) from error
