"""Decode and validate encoded profiles without external dependencies."""

import json
from typing import Protocol

from metadata_pipeline.errors import ProfileDecodeError, ProfileValidationError
from metadata_pipeline.models import MetadataProfile


class ProfileDecoder(Protocol):
    def decode(self, profile_id: str, encoded: str) -> MetadataProfile: ...


def string_list(value: object, profile_id: str, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ProfileValidationError(profile_id, f"{field} must be a list of nonblank strings")
    return tuple(value)


class JsonProfileDecoder:
    def decode(self, profile_id: str, encoded: str) -> MetadataProfile:
        try:
            value: object = json.loads(encoded)
        except json.JSONDecodeError:
            raise ProfileDecodeError(profile_id) from None
        if not isinstance(value, dict):
            raise ProfileValidationError(profile_id, "expected object")
        if set(value) != {"category", "version", "labels", "required_fields"}:
            raise ProfileValidationError(
                profile_id, "expected category, version, labels, required_fields"
            )
        category = value["category"]
        version = value["version"]
        if not isinstance(category, str) or not category.strip():
            raise ProfileValidationError(profile_id, "category must be a nonblank string")
        if type(version) is not int or version < 1:
            raise ProfileValidationError(profile_id, "version must be a positive integer")
        labels = string_list(value["labels"], profile_id, "labels")
        required = string_list(value["required_fields"], profile_id, "required_fields")
        return MetadataProfile(profile_id, category, version, labels, required)
