import pytest
from pydantic import ValidationError

from amlguard.config import EDEN_EU_BASE_URL, Settings


def test_eu_endpoint_is_locked() -> None:
    assert Settings().eden_base_url == EDEN_EU_BASE_URL
    with pytest.raises(ValidationError):
        Settings(eden_base_url="https://api.edenai.run/v3")


def test_research_mode_requires_no_implicit_credentials() -> None:
    settings = Settings(environment="research", repository_backend="postgres")
    assert settings.eden_ai_api_key is None
    assert settings.dev_auth_bypass is False


def test_database_password_reserved_characters_are_encoded() -> None:
    raw = "postgresql+asyncpg://user:p@ss:word%25@localhost:5432/amlguard"
    settings = Settings(database_url=raw)
    assert settings.database_url == (
        "postgresql+asyncpg://user:p%40ss%3Aword%25@localhost:5432/amlguard"
    )


def test_policy_jurisdiction_is_normalized() -> None:
    assert Settings(policy_jurisdiction=" fr ").policy_jurisdiction == "FR"
    with pytest.raises(ValidationError):
        Settings(policy_jurisdiction=" ")
