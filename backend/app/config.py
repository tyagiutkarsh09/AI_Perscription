from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    database_url: str

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
