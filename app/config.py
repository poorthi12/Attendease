from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mongodb_url: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("MONGODB_URL", "MONGODB_URI")
    )
    mongodb_database: str = "attendease"
    session_secret: SecretStr | None = None
    app_env: Literal["development", "test", "production"] = "development"
    cookie_secure: bool = False
    session_max_age_seconds: int = Field(default=28800, ge=300, le=604800)

    @model_validator(mode="after")
    def production_requires_secrets(self) -> "Settings":
        if self.app_env == "production":
            if not self.session_secret or len(self.session_secret.get_secret_value()) < 32:
                raise ValueError("SESSION_SECRET must contain at least 32 characters in production")
            if not self.mongodb_url:
                raise ValueError("MONGODB_URL is required in production")
            self.cookie_secure = True
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
