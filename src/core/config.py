"""
NC Code Analyser - Core Configuration
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = Field(default="NC Code Analyser", alias="APP_NAME")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Server
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    # Ollama AI
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="mistral", alias="OLLAMA_MODEL")

    # AI prompt construction
    # Number of unchanged lines of context to include above/below each
    # changed line when building the LLM analysis prompt. Larger values give
    # the model more grounding but increase token usage.
    prompt_context_lines: int = Field(default=5, alias="PROMPT_CONTEXT_LINES")
    # Maximum number of separate change hunks to include in the prompt.
    prompt_max_hunks: int = Field(default=12, alias="PROMPT_MAX_HUNKS")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/nc_analyser",
        alias="DATABASE_URL",
    )
    database_url_sync: str = Field(
        default="postgresql://postgres:password@localhost:5432/nc_analyser",
        alias="DATABASE_URL_SYNC",
    )

    # File Storage
    upload_dir: str = Field(default="./data/uploads", alias="UPLOAD_DIR")
    baseline_dir: str = Field(default="./data/baselines", alias="BASELINE_DIR")
    reports_dir: str = Field(default="./data/reports", alias="REPORTS_DIR")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        for dir_path in [
            self.upload_dir,
            self.baseline_dir,
            self.reports_dir,
        ]:
            Path(dir_path).mkdir(parents=True, exist_ok=True)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    settings = Settings()
    settings.ensure_directories()
    return settings
