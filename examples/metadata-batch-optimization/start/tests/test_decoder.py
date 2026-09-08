import json

import pytest
from metadata_pipeline import JsonProfileDecoder, ProfileDecodeError, ProfileValidationError


def test_decode_values() -> None:
    profile = JsonProfileDecoder().decode(
        "p",
        json.dumps(
            {
                "category": "events",
                "version": 2,
                "labels": ["ready", "ready"],
                "required_fields": ["amount"],
            }
        ),
    )
    assert (profile.profile_id, profile.category, profile.version) == ("p", "events", 2)
    assert profile.labels == ("ready", "ready")
    assert profile.required_fields == ("amount",)


def test_malformed_json() -> None:
    with pytest.raises(ProfileDecodeError, match="Invalid JSON for profile: p"):
        JsonProfileDecoder().decode("p", "{")


@pytest.mark.parametrize(
    "value", [[], {}, {"category": "events", "version": True, "labels": [], "required_fields": []}]
)
def test_invalid_structure(value: object) -> None:
    with pytest.raises(ProfileValidationError):
        JsonProfileDecoder().decode("p", json.dumps(value))
