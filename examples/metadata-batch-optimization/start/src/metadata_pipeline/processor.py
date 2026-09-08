"""Ordered enrichment through repository and decoding collaborators."""

from collections.abc import Sequence
from copy import deepcopy

from metadata_pipeline.decoder import ProfileDecoder
from metadata_pipeline.errors import RecordValidationError
from metadata_pipeline.models import EnrichedRecord, InputRecord, MetadataProfile
from metadata_pipeline.repository import ProfileRepository


def validate_record(record: InputRecord, profile: MetadataProfile) -> None:
    missing = tuple(field for field in profile.required_fields if field not in record.payload)
    if missing:
        raise RecordValidationError(record.record_id, missing)


def render_record(record: InputRecord, profile: MetadataProfile) -> EnrichedRecord:
    return EnrichedRecord(
        record.record_id,
        record.profile_id,
        deepcopy(record.payload),
        profile.category,
        profile.version,
        list(profile.labels),
    )


class BatchProcessor:
    def __init__(self, repository: ProfileRepository, decoder: ProfileDecoder) -> None:
        self._repository = repository
        self._decoder = decoder

    def enrich(self, records: Sequence[InputRecord]) -> list[EnrichedRecord]:
        result = []
        for record in records:
            encoded = self._repository.get_encoded(record.profile_id)
            profile = self._decoder.decode(record.profile_id, encoded)
            validate_record(record, profile)
            result.append(render_record(record, profile))
        return result
