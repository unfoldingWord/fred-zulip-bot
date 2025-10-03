from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration sourced from environment variables."""

    model_config = SettingsConfigDict(env_file="./.env", extra="ignore")

    # Test variables (optional)
    ZULIP_BOT_TOKEN_TEST: Optional[str] = None
    ZULIP_BOT_EMAIL_TEST: Optional[str] = None
    ZULIP_AUTH_TOKEN_TEST: Optional[str] = None

    TEST_MODE: bool = False

    # Required variables
    ZULIP_BOT_TOKEN: str
    ZULIP_BOT_EMAIL: str
    ZULIP_SITE: str
    DB_HOST: str
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    GENAI_API_KEY: str
    ZULIP_AUTH_TOKEN: str

    # History storage configuration
    HISTORY_BACKEND: str = "tinydb"
    HISTORY_DB_PATH: str = "./data/history.json"
    HISTORY_FILES_DIR: str = "./data/chat_histories"
    HISTORY_MAX_LENGTH: int = 20


config = Config()  # type: ignore[call-arg]
