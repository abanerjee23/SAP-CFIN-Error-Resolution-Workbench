from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_publishable_key: SecretStr = SecretStr("")
    supabase_secret_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    arize_enabled: bool = False
    arize_api_key: SecretStr = SecretStr("")
    arize_space_id: str = ""
    arize_project_name: str = "cfin-document-error-analysis"
    arize_api_url: str = "https://api.arize.com/v2"
    arize_otlp_endpoint: str = "https://otlp.arize.com/v1/traces"
    paid_models_enabled: bool = False
    log_only_enabled: bool = False
    local_demo_enabled: bool = False
    demo_workspace_id: UUID | None = None
    demo_actor_id: UUID | None = None
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    model_agent_1: str = "gpt-6-luna"
    model_agent_2: str = "gpt-6.1-sol"
    model_agent_3: str = "gpt-6.1-sol"
    model_agent_4: str = ""
    model_reasoning_effort: Literal["low", "medium", "high"] = "medium"
    error_analysis_profile: Literal[
        "baseline", "compact", "fast", "writer_luna", "writer_low", "all_luna"
    ] = "baseline"
    model_monthly_budget_usd: Decimal = Field(default=Decimal("10.00"), gt=0, le=10)
    model_run_budget_usd: Decimal = Field(default=Decimal("1.00"), gt=0, le=1)
    stage_timeout_seconds: int = Field(default=60, gt=0, le=60)
    stage_max_retries: int = Field(default=1, ge=0, le=1)

    @property
    def worker_configured(self) -> bool:
        return bool(self.cloud_configured and self.supabase_secret_key.get_secret_value())

    @property
    def arize_configured(self) -> bool:
        return bool(
            self.arize_enabled
            and self.arize_api_key.get_secret_value().strip()
            and self.arize_space_id.strip()
            and self.arize_project_name.strip()
        )

    @field_validator("arize_api_url", "arize_otlp_endpoint")
    @classmethod
    def validate_arize_url(cls, value: str) -> str:
        value = value.rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Arize endpoints must use HTTPS without credentials, query or fragment"
            )
        return value

    @property
    def models_configured(self) -> bool:
        return bool(
            self.paid_models_enabled
            and self.openai_api_key.get_secret_value()
            and all((self.model_agent_1, self.model_agent_2, self.model_agent_3))
        )

    @field_validator("supabase_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if value and not value.startswith("https://"):
            raise ValueError("Cloud Supabase URL must use HTTPS")
        return value

    @property
    def cloud_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_publishable_key.get_secret_value())
