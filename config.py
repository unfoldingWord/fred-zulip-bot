from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

class Config(BaseSettings):

    # Test variables (optional)
    ZULIP_BOT_TOKEN_TEST: Optional[str] = Field(None, env="ZULIP_BOT_TOKEN_TEST")
    ZULIP_BOT_EMAIL_TEST: Optional[str] = Field(None, env="ZULIP_BOT_EMAIL_TEST")
    ZULIP_AUTH_TOKEN_TEST: Optional[str] = Field(None, env="ZULIP_AUTH_TOKEN_TEST")

    TEST_MODE: Optional[bool] = Field(False, env="TEST_MODE")

    # Required variables
    ZULIP_BOT_TOKEN: str = Field(..., env="ZULIP_BOT_TOKEN")
    ZULIP_BOT_EMAIL: str = Field(..., env="ZULIP_BOT_EMAIL")
    ZULIP_SITE:str = Field(..., env="ZULIP_SITE")
    DB_HOST:str = Field(..., env="DB_HOST")
    DB_NAME:str = Field(..., env="DB_NAME")
    DB_USER:str = Field(..., env="DB_USER")
    DB_PASSWORD:str = Field(..., env="DB_PASSWORD")
    GENAI_API_KEY:str = Field(..., env="GENAI_API_KEY")
    ZULIP_AUTH_TOKEN:str = Field(..., env="ZULIP_AUTH_TOKEN")

    # History storage configuration
    HISTORY_BACKEND: str = Field("tinydb", env="HISTORY_BACKEND")
    HISTORY_DB_PATH: str = Field("./data/history.json", env="HISTORY_DB_PATH")
    HISTORY_FILES_DIR: str = Field("./data/chat_histories", env="HISTORY_FILES_DIR")
    HISTORY_MAX_LENGTH: int = Field(20, env="HISTORY_MAX_LENGTH")

    class Config:
        env_file = "./.env"

config = Config()
