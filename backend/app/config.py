"""Application settings.

Every value can be overridden by an environment variable of the same name
(case-insensitive) or by the repo-root `.env` file. Nothing else in the code
reads `os.environ` directly — this module is the single entry point for config.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    openai_api_key: SecretStr | None = None
    llm_model: str = "gpt-6-luna"
    llm_reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] | None = "low"
    llm_temperature: float = 0.1  # ignored by reasoning models
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 3
    agent_max_iterations: int = 8
    agent_timeout_s: float = 120.0
    # USD per 1M tokens, for the cost shown per answer (defaults: gpt-6-luna list price).
    # Update when changing the model; set to empty to show tokens only.
    llm_price_input_per_mtok: float | None = 0.10
    llm_price_output_per_mtok: float | None = 0.50

    # --- Retrieval ---
    embed_model: str = "BAAI/bge-small-en-v1.5"
    retrieval_top_k: int = 5

    # --- Paths ---
    data_dir: Path = REPO_ROOT / "data"
    var_dir: Path = REPO_ROOT / "var"

    # --- Business context ---
    company_timezone: str = "America/Chicago"

    # --- API ---
    cors_origins: list[str] = ["http://localhost:3000"]
    rate_limit_enabled: bool = False
    rate_limit: str = "20/minute"
    max_message_chars: int = 2000

    # --- Sessions ---
    session_ttl_s: int = 60 * 60
    max_sessions: int = 1000
    history_token_limit: int = 8000
    history_max_turns: int = 10

    # --- SQL tool ---
    sql_row_limit: int = 50
    data_refresh_check_s: int = 600  # reseed check interval (dates are relative)

    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"  # json: one object per line, for log collectors

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "docs"

    @property
    def manifest_path(self) -> Path:
        return self.docs_dir / "manifest.yaml"

    @property
    def models_dir(self) -> Path:
        return self.var_dir / "models"

    @property
    def facts_path(self) -> Path:
        return self.data_dir / "company" / "facts.yaml"

    @property
    def db_path(self) -> Path:
        return self.var_dir / "logistics.db"

    @property
    def index_dir(self) -> Path:
        return self.var_dir / "index"


@lru_cache
def get_settings() -> Settings:
    return Settings()
