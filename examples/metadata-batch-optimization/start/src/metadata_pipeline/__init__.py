"""Public API for the metadata enrichment library."""

from metadata_pipeline.decoder import JsonProfileDecoder, ProfileDecoder
from metadata_pipeline.errors import (
    MissingProfileError,
    ProfileDecodeError,
    ProfileValidationError,
    RecordValidationError,
)
from metadata_pipeline.models import EnrichedRecord, InputRecord, MetadataProfile
from metadata_pipeline.processor import BatchProcessor
from metadata_pipeline.repository import InMemoryProfileRepository, ProfileRepository

__all__ = [
    "BatchProcessor",
    "EnrichedRecord",
    "InMemoryProfileRepository",
    "InputRecord",
    "JsonProfileDecoder",
    "MetadataProfile",
    "MissingProfileError",
    "ProfileDecodeError",
    "ProfileDecoder",
    "ProfileRepository",
    "ProfileValidationError",
    "RecordValidationError",
]
