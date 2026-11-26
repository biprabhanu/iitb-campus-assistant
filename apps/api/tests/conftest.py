"""Shared pytest setup (lead-owned).

Every test runs offline and isolated:
- settings are rebuilt per test, ignoring the developer's real `.env`;
- the DB and raw dir point into a temp folder;
- keyring uses an in-memory backend, so tests never touch the real macOS Keychain.
"""

from __future__ import annotations

from collections.abc import Iterator

import keyring
import pytest
from keyring.backend import KeyringBackend

from campuspilot import config


class MemoryKeyring(KeyringBackend):
    """A throwaway keyring that lives only for one test."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch) -> Iterator[None]:
    # Don't read the developer's .env during tests.
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    for name in ("MOODLE_TOKEN", "MOODLE_ICAL_URL", "LLM_FALLBACK_ENABLED", "CAMPUSPILOT_MOCK_LLM"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CAMPUSPILOT_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CAMPUSPILOT_RAW_DIR", str(tmp_path / "raw"))
    # Scripted LLMs in tests don't expect the extra clarify call; tests that need it opt in.
    monkeypatch.setenv("CLARIFY_PRECHECK", "false")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def memory_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)
