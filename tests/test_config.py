import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def test_settings_accept_legacy_mongodb_uri(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://example.invalid")
    settings = Settings(_env_file=None, app_env="test")
    assert isinstance(settings.mongodb_url, SecretStr)
    assert settings.mongodb_url.get_secret_value() == "mongodb://example.invalid"


def test_production_requires_a_strong_session_secret():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", mongodb_url=None, session_secret=None)
