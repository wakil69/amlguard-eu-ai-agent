from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EDEN_EU_BASE_URL = "https://api.eu.edenai.run/v3"


class Settings(BaseSettings):
    """Process settings; secret values are never serialized into telemetry."""

    model_config = SettingsConfigDict(env_prefix="AMLGUARD_", extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "research"] = "development"
    repository_backend: Literal["memory", "postgres"] = "memory"
    database_url: str = "postgresql+asyncpg://amlguard:amlguard@localhost:5432/amlguard"
    database_dsn: str = (
        "postgresql://amlguard:amlguard@localhost:5432/amlguard?options=-csearch_path%3Dlanggraph"
    )
    keycloak_issuer: AnyHttpUrl = AnyHttpUrl("http://localhost:8081/realms/amlguard")
    keycloak_internal_url: AnyHttpUrl | None = None
    keycloak_audience: str = "amlguard-api"
    keycloak_client_id: str = "amlguard-web"
    keycloak_client_secret: SecretStr | None = None
    session_secret: SecretStr = SecretStr("development-only-change-me")
    dev_auth_bypass: bool = False

    eden_ai_api_key: SecretStr | None = None
    eden_model_id: str | None = None
    eden_base_url: str = EDEN_EU_BASE_URL
    llm_timeout_seconds: float = Field(default=45.0, ge=1, le=300)
    llm_kill_switch: bool = False

    otel_endpoint: AnyHttpUrl = AnyHttpUrl("http://localhost:4318")
    otel_health_endpoint: AnyHttpUrl = AnyHttpUrl("http://localhost:13133")
    otel_enabled: bool = True
    artifact_root: Path = Path(".artifacts")
    artifact_key_file: Path | None = None
    raw_research_capture: bool = True
    policy_corpus_root: Path = Path("regulatory_corpus")
    policy_jurisdiction: str = Field(default="FR", min_length=2, max_length=20)
    policy_result_limit: int = Field(default=20, ge=15, le=20)
    experiment_kill_switch: bool = False
    worker_concurrency: int = Field(default=2, ge=1, le=32)

    @field_validator("database_url", "database_dsn", mode="before")
    @classmethod
    def encode_database_userinfo(cls, value: object) -> object:
        """Accept human-entered passwords containing reserved URL characters."""
        if not isinstance(value, str) or "://" not in value:
            return value
        parsed = urlsplit(value)
        if parsed.username is None or parsed.hostname is None:
            return value
        username = quote(unquote(parsed.username), safe="")
        password = (
            f":{quote(unquote(parsed.password), safe='')}" if parsed.password is not None else ""
        )
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        port = f":{parsed.port}" if parsed.port is not None else ""
        return urlunsplit(
            (parsed.scheme, f"{username}{password}@{host}{port}", parsed.path, parsed.query, "")
        )

    @property
    def keycloak_backend(self) -> str:
        return str(self.keycloak_internal_url or self.keycloak_issuer).rstrip("/")

    @field_validator("eden_base_url")
    @classmethod
    def require_eu_endpoint(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if normalized != EDEN_EU_BASE_URL:
            raise ValueError(f"Eden inference must use {EDEN_EU_BASE_URL}")
        return normalized

    @field_validator("eden_ai_api_key", mode="before")
    @classmethod
    def blank_secret_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("eden_model_id", mode="before")
    @classmethod
    def blank_model_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("policy_jurisdiction", mode="before")
    @classmethod
    def normalize_policy_jurisdiction(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("keycloak_internal_url", mode="before")
    @classmethod
    def blank_internal_url_is_none(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    env_file = os.getenv("AMLGUARD_ENV_FILE") or ".env.dev"
    return Settings(_env_file=env_file)
