"""Config loading (lead-owned smoke test)."""

from campuspilot.config import REPO_ROOT, get_settings


def test_defaults_are_local_and_safe(monkeypatch):
    s = get_settings()
    assert s.api_host == "127.0.0.1"
    assert s.ollama_base_url.startswith("http://127.0.0.1")
    assert s.llm_fallback_enabled is False
    assert s.allow_personal_data_to_cloud is False
    assert s.max_tool_calls == 4
    assert "http://127.0.0.1:3000" in s.cors_origins


def test_relative_paths_resolve_against_repo_root(monkeypatch):
    monkeypatch.setenv("CAMPUSPILOT_DB_PATH", "data/x.db")
    get_settings.cache_clear()
    assert get_settings().campuspilot_db_path == REPO_ROOT / "data" / "x.db"


def test_secrets_are_masked(monkeypatch):
    monkeypatch.setenv("MOODLE_TOKEN", "abc123secret")
    get_settings.cache_clear()
    s = get_settings()
    assert "abc123secret" not in repr(s)
    assert s.moodle_token.get_secret_value() == "abc123secret"
