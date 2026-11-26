"""Application settings, read from environment variables and the repo-root `.env`.

Every module gets settings through `get_settings()` so tests can override them
with `get_settings.cache_clear()` plus `monkeypatch.setenv(...)`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/campuspilot/config.py -> parents[3] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM (Ollama on Passpoli, reached through the SSH tunnel) ---
    ollama_base_url: str = "http://127.0.0.1:11500"
    ollama_model: str = "gemma4:26b-a4b-it-q4_K_M"
    # Generous read timeout: a cold model load takes ~7-10 s, long answers more.
    ollama_timeout_s: float = 120.0
    ollama_connect_timeout_s: float = 5.0
    campuspilot_mock_llm: bool = False

    # --- Optional OpenAI-compatible fallback (off by default) ---
    llm_fallback_enabled: bool = False
    llm_fallback_base_url: str = ""
    llm_fallback_api_key: SecretStr = SecretStr("")
    llm_fallback_model: str = ""
    # Personal data (Moodle results) never goes to a cloud LLM unless this is true.
    allow_personal_data_to_cloud: bool = False

    # --- Moodle (read-only) ---
    moodle_base_url: str = "https://moodle.iitb.ac.in"
    moodle_token: SecretStr = SecretStr("")
    moodle_ical_url: SecretStr = SecretStr("")
    # When no token / iCal URL is configured, serve clearly-labelled fixture data.
    moodle_demo_when_unconfigured: bool = True
    moodle_timeout_s: float = 10.0
    moodle_cache_ttl_s: int = 300

    # --- Storage ---
    campuspilot_db_path: Path = REPO_ROOT / "data" / "campuspilot.db"
    campuspilot_raw_dir: Path = REPO_ROOT / "data" / "raw"
    campuspilot_registry_csv: Path = REPO_ROOT / "data" / "sources" / "registry.csv"

    # --- API server ---
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:3000", "http://localhost:3000"]
    )
    rate_limit_per_min: int = 30
    tool_timeout_s: float = 15.0
    max_tool_calls: int = 4
    max_history_turns: int = 20
    # One short extra model call that decides "ask a clarifying question?" (agent/clarify.py).
    clarify_precheck: bool = True
    # After a document search, also look up registry portal links (agent/orchestrator.py).
    auto_official_links: bool = True

    @field_validator(
        "campuspilot_db_path", "campuspilot_raw_dir", "campuspilot_registry_csv", mode="after"
    )
    @classmethod
    def _resolve_against_repo_root(cls, value: Path) -> Path:
        # Relative paths in .env mean "relative to the repo root", whatever the cwd is.
        return value if value.is_absolute() else REPO_ROOT / value


@lru_cache
def get_settings() -> Settings:
    return Settings()
