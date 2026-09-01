from pathlib import Path

from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database — postgres service name inside Docker; localhost override for local dev
    # docker-compose.yml overrides via DATABASE_URL env; default uses postgres:5432
    database_url: str = "postgresql+asyncpg://internapply:changeme@postgres:5432/internapply"

    # OpenCode Go
    opencode_go_api_key: str = ""
    opencode_go_model: str = "deepseek-v4-flash"
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"

    # Hunter
    hunter_api_key: str = ""

    # Proxy
    proxy_url: str = "socks5://localhost:8888"

    # Gmail
    gmail_sender_email: str = ""
    gmail_client_secret_path: str = ""

    # Discovery preferences
    search_keywords: list[str] = ["python backend intern", "java spring boot intern"]
    search_locations: list[str] = ["Remote", "Bangalore"]
    min_stipend_inr: int = 5000
    log_level: str = "INFO"

    # Hash/Dedup & Boards — mirrors internapply/config.py
    HASH_SALT: str = Field(default="internapply-v1")
    SIMHASH_THRESHOLD: int = Field(default=3, ge=1, le=10)
    VERIFIER_MIN_SCORE: int = Field(default=80, ge=0, le=100)
    HIRIST_ENABLED: bool = True
    UNSTOP_ENABLED: bool = True
    ARBEITNOW_ENABLED: bool = True
    REMOTIVE_ENABLED: bool = True
    THEMUSE_ENABLED: bool = True
    JOBICY_ENABLED: bool = True
    WREQ_SIDECAR_URL: str = ""
    VOLLNA_RSS_URL: str = ""

    @property
    def ats_boards(self) -> list[dict]:
        import json

        p = Path("config/boards.json")
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text())
            boards = data.get("working", [])
            if len(boards) < 50:
                logger.warning("boards.json working {} <50, check probe", len(boards))
            return boards
        except Exception as e:
            logger.warning("failed to load boards.json: {}", e)
            return []

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
