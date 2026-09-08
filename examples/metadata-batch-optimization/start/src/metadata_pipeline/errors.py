"""Stable domain diagnostics used by callers of the enrichment pipeline."""


class MissingProfileError(LookupError):
    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        super().__init__(f"Profile not found: {profile_id}")


class ProfileDecodeError(ValueError):
    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        super().__init__(f"Invalid JSON for profile: {profile_id}")


class ProfileValidationError(ValueError):
    def __init__(self, profile_id: str, reason: str) -> None:
        self.profile_id = profile_id
        self.reason = reason
        super().__init__(f"Invalid profile {profile_id}: {reason}")


class RecordValidationError(ValueError):
    def __init__(self, record_id: str, missing_fields: tuple[str, ...]) -> None:
        self.record_id = record_id
        self.missing_fields = missing_fields
        super().__init__(f"Record {record_id} missing fields: {', '.join(missing_fields)}")
