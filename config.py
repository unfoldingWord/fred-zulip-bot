from pydantic_settings import BaseSettings
from pydantic import Field

class Config(BaseSettings):
    ZULIP_BOT_TOKEN: str = Field(..., env="ZULIP_BOT_TOKEN")
    ZULIP_BOT_EMAIL: str = Field(..., env="ZULIP_BOT_EMAIL")
    ZULIP_SITE:str = Field(..., env="ZULIP_SITE")
    DB_HOST:str = Field(..., env="DB_HOST")
    DB_NAME:str = Field(..., env="DB_NAME")
    DB_USER:str = Field(..., env="DB_USER")
    DB_PASSWORD:str = Field(..., env="DB_PASSWORD")
    GENAI_API_KEY:str = Field(..., env="GENAI_API_KEY")

    class Config:
        env_file = "./.venv/.env"

config = Config()