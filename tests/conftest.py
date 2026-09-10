"""Pytest configuration."""

import pytest


@pytest.fixture(autouse=True)
def _production_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the real path unless a test says otherwise.

    Effect gates resolve from the environment, and an unset environment
    resolves to local — which would suppress every trigger and every ping
    and quietly turn this suite into a test of the suppression branch.
    Tests that want the suppressed path set ENVIRONMENT themselves.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("PREFECT_TRIGGER_ENABLED", raising=False)
    monkeypatch.delenv("HEALTHCHECKS_ENABLED", raising=False)


class DummyDriveFile:
    def __init__(self, file_id: str, name: str = "file.txt") -> None:
        self.id = file_id
        self.name = name
        self.mime_type = None
        self.modified_time = None


@pytest.fixture
def dummy_drive_file() -> type[DummyDriveFile]:
    return DummyDriveFile
