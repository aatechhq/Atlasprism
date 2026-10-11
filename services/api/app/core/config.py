"""Configuration. Validated at import; no secret is ever logged or returned."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://prism:prism@localhost:5432/atlas_prism",
        alias="DATABASE_URL",
    )

    # --- Auth ---
    jwt_secret: str = Field(default="dev-only-insecure-secret", alias="JWT_SECRET")
    jwt_expire_minutes: int = Field(default=720, alias="JWT_EXPIRE_MINUTES")
    admin_email: str = Field(default="admin@example.com", alias="ADMIN_EMAIL")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")

    # --- N-ATLAS gateway (PRD 7) ---
    natlas_base_url: str = Field(default="", alias="NATLAS_BASE_URL")
    natlas_api_key: str = Field(default="", alias="NATLAS_API_KEY")
    natlas_model_id: str = Field(default="NCAIR1/N-ATLaS", alias="NATLAS_MODEL_ID")
    natlas_timeout_ms: int = Field(default=60000, alias="NATLAS_TIMEOUT_MS")
    natlas_allowed_hosts: str = Field(default="", alias="NATLAS_ALLOWED_HOSTS")

    # --- Execution bounds (runaway-cost protection) ---
    run_max_concurrency: int = Field(default=2, alias="RUN_MAX_CONCURRENCY")
    run_max_cases: int = Field(default=200, alias="RUN_MAX_CASES")
    run_max_repeats: int = Field(default=5, alias="RUN_MAX_REPEATS")

    @field_validator("natlas_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def allowed_inference_hosts(self) -> set[str]:
        """SSRF allowlist. Inference is never sent to a host outside this set."""
        hosts = {h.strip().lower() for h in self.natlas_allowed_hosts.split(",") if h.strip()}
        if not hosts and self.natlas_base_url:
            parsed = urlparse(self.natlas_base_url)
            if parsed.hostname:
                hosts.add(parsed.hostname.lower())
        return hosts

    @property
    def natlas_credentials_present(self) -> bool:
        """False means: report blocked, never fake a success."""
        return bool(self.natlas_api_key.strip())

    @property
    def natlas_timeout_seconds(self) -> float:
        return max(1.0, self.natlas_timeout_ms / 1000.0)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
