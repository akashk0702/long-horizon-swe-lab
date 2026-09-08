import pytest
from metadata_pipeline import InMemoryProfileRepository, MissingProfileError


def test_storage_updates_and_removal() -> None:
    source = {"p": "first"}
    repository = InMemoryProfileRepository(source)
    source["p"] = "changed"
    assert repository.get_encoded("p") == "first"
    repository.set_encoded("p", "second")
    assert repository.get_encoded("p") == "second"
    assert repository.remove("p") is True
    assert repository.remove("p") is False


def test_missing_has_stable_diagnostic() -> None:
    with pytest.raises(MissingProfileError) as error:
        InMemoryProfileRepository().get_encoded("absent")
    assert error.value.profile_id == "absent"
    assert str(error.value) == "Profile not found: absent"
