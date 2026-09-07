from pathlib import Path

import pytest
import yaml


@pytest.fixture
def task_data() -> dict:
    return {
        "id": "contract-check",
        "title": "Validate a task contract",
        "description": "A temporary contract used by the foundation test suite.",
        "workspace": "repository",
        "timeout_seconds": 30,
        "verification_command": ["python", "-m", "pytest"],
        "allowed_paths": ["src", "tests"],
        "metadata": {"category": "contract-test", "revision": 1},
    }


@pytest.fixture
def manifest(tmp_path: Path, task_data: dict) -> Path:
    (tmp_path / "repository").mkdir()
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump(task_data), encoding="utf-8")
    return path
