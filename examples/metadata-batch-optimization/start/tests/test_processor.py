import json

import pytest
from metadata_pipeline import (
    BatchProcessor,
    InMemoryProfileRepository,
    InputRecord,
    JsonProfileDecoder,
    RecordValidationError,
)


def pipeline() -> BatchProcessor:
    return BatchProcessor(
        InMemoryProfileRepository(
            {
                "p": json.dumps(
                    {
                        "category": "events",
                        "version": 1,
                        "labels": ["ready"],
                        "required_fields": ["x"],
                    }
                )
            }
        ),
        JsonProfileDecoder(),
    )


def test_empty() -> None:
    assert pipeline().enrich([]) == []


def test_order_duplicates_and_payload_values() -> None:
    records = [InputRecord("same", "p", {"x": 2}), InputRecord("same", "p", {"x": 1})]
    output = pipeline().enrich(records)
    assert [item.record_id for item in output] == ["same", "same"]
    assert [item.payload for item in output] == [{"x": 2}, {"x": 1}]
    assert all(item.category == "events" and item.version == 1 for item in output)


def test_output_mutation_does_not_change_inputs_or_siblings() -> None:
    record = InputRecord("r", "p", {"x": [1]})
    output = pipeline().enrich([record, record])
    output[0].payload["x"] = [9]
    output[0].labels.append("changed")
    assert record.payload == {"x": [1]}
    assert output[1].payload == {"x": [1]}
    assert output[1].labels == ["ready"]


def test_required_field_error() -> None:
    with pytest.raises(RecordValidationError) as error:
        pipeline().enrich([InputRecord("r", "p", {})])
    assert error.value.record_id == "r"
    assert error.value.missing_fields == ("x",)
    assert str(error.value) == "Record r missing fields: x"
