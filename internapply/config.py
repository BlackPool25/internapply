"""Configuration loader for InternApply.

Uses pydantic-settings BaseSettings to load from environment variables
and .env files. Provides a lazy singleton via get_config().
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv
from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Load .env at module level so that os.getenv() and pydantic-settings
#    both pick up values from the file.  This is safe because we do NOT
#    instantiate Config here (no import-time config creation).
_dotenv_loaded = False


def _ensure_env_loaded() -> None:
    """Load .env from the project root (or cwd) exactly once."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return

    # Try several locations in priority order
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",  # project root
        Path(__file__).resolve().parent.parent.parent / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate, override=False)
            logger.debug("Loaded .env from {}", candidate)
            break
    else:
        logger.debug("No .env file found – relying on environment variables")

    _dotenv_loaded = True


def _mask_key(key: str, visible: int = 4) -> str:
    """Return a sanitized version of an API key (show first *visible* chars)."""
    if not key:
        return "<empty>"
    if len(key) <= visible:
        return key[:visible] + "***"
    return key[:visible] + "****" + key[-4:] if len(key) > visible + 4 else key[:visible] + "***"


class Config(BaseSettings):
    """Application configuration.

    All values are read from environment variables or a ``.env`` file.
    Instances are frozen — once created the config is immutable.
    """

    # ── Required ──────────────────────────────────────────────────────
    OPENCODE_GO_API_KEY: str = Field(
        default="",
        description="OpenCode Go API key (required for LLM calls)",
    )

    # ── Optional — LLM ───────────────────────────────────────────────
    OPENCODE_GO_MODEL: str = Field(
        default="opencode-go/deepseek-v4-flash",
        description="Model identifier for OpenCode Go LLM",
    )
    OPENCODE_GO_BASE_URL: str = Field(
        default="https://opencode.ai/zen/go/v1",
        description="Base URL for the OpenCode Go API",
    )

    # ── Optional — Email & Discovery ─────────────────────────────────
    HUNTER_API_KEY: str = Field(default="", description="Hunter.io API key for email discovery")
    GMAIL_SENDER_EMAIL: str = Field(default="", description="Gmail address used for sending applications")
    GMAIL_CLIENT_SECRET_PATH: str = Field(default="", description="Path to Gmail OAuth client_secret.json")

    # ── Preferences ──────────────────────────────────────────────────
    SEARCH_KEYWORDS: list[str] = Field(
        default=["python backend intern", "java spring boot intern", "backend engineer intern"],
        description="Keywords used to search for internship listings",
    )
    SEARCH_LOCATIONS: list[str] = Field(
        default=["Remote", "Bangalore"],
        description="Target locations for internship search",
    )
    MIN_STIPEND_INR: int = Field(default=5000, ge=0, description="Minimum monthly stipend in INR")
    MAX_APPLICATIONS_PER_DAY: int = Field(default=20, ge=1, description="Daily application limit")
    DATABASE_PATH: str = Field(
        default="data/internapply.db",
        description="Path to the SQLite database file",
    )
    LOG_LEVEL: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)")
    NAUKRI_APIFY_TOKEN: str = Field(default="", description="Apify token for enriched Naukri data")

    # ── Pydantic-settings config ─────────────────────────────────────
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    def model_post_init(self, __context, /) -> None:
        """Log a summary of the loaded configuration (with masked secrets)."""
        _ensure_env_loaded()
        _log_config(self)


# ── Singleton holder ──────────────────────────────────────────────────

_ConfigT = Config | None
_instance: _ConfigT = None
_loaded = False


def get_config() -> Config:
    """Return the application-wide Config singleton.

    The config is lazily loaded on the first call — environment variables
    and ``.env`` files are read at that point.  Subsequent calls return the
    same frozen instance.
    """
    global _instance, _loaded
    if not _loaded:
        _ensure_env_loaded()
        _instance = Config()
        _loaded = True
    assert _instance is not None
    return _instance


def reload_config() -> Config:
    """Force a fresh reload of the configuration.

    Useful in tests or after changing environment variables at runtime.
    """
    global _instance, _loaded
    _ensure_env_loaded()
    _instance = Config()
    _loaded = True
    return _instance


# ── Internal helpers ──────────────────────────────────────────────────

_OPTIONAL_KEYS = {
    "HUNTER_API_KEY",
    "GMAIL_SENDER_EMAIL",
    "GMAIL_CLIENT_SECRET_PATH",
    "NAUKRI_APIFY_TOKEN",
}


def _log_config(cfg: Config) -> None:
    """Log each config field, masking secrets."""
    logger.info("── Configuration ──────────────────────────────────")
    for field_name in cfg.model_fields:
        raw = getattr(cfg, field_name)
        masked = _mask_value(field_name, raw)
        logger.info("  {:32s} = {}", field_name, masked)

    # Warn about missing optional fields that may affect functionality
    for key in sorted(_OPTIONAL_KEYS):
        value: str = getattr(cfg, key, "")
        if not value:
            logger.warning("  {} is not set — related features will be unavailable", key)
    logger.info("────────────────────────────────────────────────────")


def _mask_value(field_name: str, value: object) -> str:
    """Return a display-safe representation of *value* for *field_name*."""
    # Mask anything that looks like an API key / token / secret
    lower = field_name.lower()
    if lower.endswith(("api_key", "_token", "_secret", "_secret_path")) or "_api_key" in lower:
        return _mask_key(str(value)) if value else "<empty>"

    if isinstance(value, list):
        return repr(value)

    return str(value) if value else "<empty>"


__all__ = ["Config", "get_config", "reload_config"]
