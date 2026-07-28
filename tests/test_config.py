"""Tests for configuration loader.

Verifies that Config (pydantic-settings BaseSettings) loads with correct
defaults and reads from environment variables when set.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from internapply.config import Config, reload_config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfig:
    """Configuration defaults and environment variable overrides."""

    def test_config_defaults(self, monkeypatch):
        """Config loads with correct default values when no env vars override."""
        # Clear any env vars that could override defaults
        for key in Config.model_fields:
            monkeypatch.delenv(key, raising=False)

        cfg = Config()

        assert cfg.MIN_STIPEND_INR == 5000
        assert cfg.MAX_APPLICATIONS_PER_DAY == 20
        assert cfg.LOG_LEVEL == "INFO"
        assert cfg.DATABASE_PATH == "data/internapply.db"
        assert cfg.SEARCH_KEYWORDS == [
            "python backend intern",
            "java spring boot intern",
            "backend engineer intern",
        ]
        assert cfg.SEARCH_LOCATIONS == ["Remote", "Bangalore"]
        assert cfg.OPENCODE_GO_MODEL == "opencode-go/deepseek-v4-flash"
        assert cfg.OPENCODE_GO_BASE_URL == "https://opencode.ai/zen/go/v1"

    def test_config_defaults_optional_empty(self, monkeypatch):
        """Optional API keys default to empty string."""
        for key in Config.model_fields:
            monkeypatch.delenv(key, raising=False)

        cfg = Config()

        assert cfg.HUNTER_API_KEY == ""
        assert cfg.GMAIL_SENDER_EMAIL == ""
        assert cfg.GMAIL_CLIENT_SECRET_PATH == ""
        assert cfg.NAUKRI_APIFY_TOKEN == ""
        assert cfg.OPENCODE_GO_API_KEY == ""

    def test_config_from_env(self, monkeypatch):
        """Config reads integer and string values from environment variables."""
        for key in Config.model_fields:
            monkeypatch.delenv(key, raising=False)

        monkeypatch.setenv("MIN_STIPEND_INR", "10000")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("MAX_APPLICATIONS_PER_DAY", "30")
        monkeypatch.setenv("DATABASE_PATH", "/tmp/test.db")
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "sk-test-key-12345")

        cfg = Config()

        assert cfg.MIN_STIPEND_INR == 10000
        assert cfg.LOG_LEVEL == "DEBUG"
        assert cfg.MAX_APPLICATIONS_PER_DAY == 30
        assert cfg.DATABASE_PATH == "/tmp/test.db"
        assert cfg.OPENCODE_GO_API_KEY == "sk-test-key-12345"

    def test_config_from_env_list_fields(self, monkeypatch):
        """Config reads list fields from environment (JSON-encoded)."""
        for key in Config.model_fields:
            monkeypatch.delenv(key, raising=False)

        monkeypatch.setenv("SEARCH_KEYWORDS", '["rust backend", "go backend"]')
        monkeypatch.setenv("SEARCH_LOCATIONS", '["Remote", "Mumbai"]')

        cfg = Config()

        assert cfg.SEARCH_KEYWORDS == ["rust backend", "go backend"]
        assert cfg.SEARCH_LOCATIONS == ["Remote", "Mumbai"]

    def test_config_frozen(self, monkeypatch):
        """Config instances are frozen — attempting mutation raises."""
        for key in Config.model_fields:
            monkeypatch.delenv(key, raising=False)

        cfg = Config()

        with pytest.raises((TypeError, ValidationError)):
            cfg.MIN_STIPEND_INR = 9999  # type: ignore[misc]
