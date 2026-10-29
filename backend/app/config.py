from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"

# Default workspace: dedicated directory under Orion's writable data area,
# not the source-code repository.
_DEFAULT_WORKSPACE_ROOT = _PROJECT_ROOT / "data" / "workspace"


class Settings(BaseSettings):
    app_name: str = "Orion"
    app_version: str = "0.1.0"
    environment: str = "development"

    nebius_api_key: str
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    nebius_model: str = "nvidia/nemotron-3-super-120b-a12b"

    # Hermes Agent (NemoClaw/OpenShell sandbox) settings.
    hermes_gateway_token: str = ""
    hermes_base_url: str = "http://127.0.0.1:8642/v1"
    hermes_model: str = "hermes-agent"

    orion_demo_key: str = ""

    # Dedicated workspace root for AI tool operations.
    # Defaults to data/workspace under Orion's writable data area.
    orion_workspace_root: str = str(_DEFAULT_WORKSPACE_ROOT)

    model_timeout_seconds: float = 60.0

    model_config = SettingsConfigDict(
        env_file=(_ENV_FILE, ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.environment.lower() in ("production", "prod"):
            if not self.orion_demo_key or not self.orion_demo_key.strip():
                raise ValueError("ORION_DEMO_KEY must be set in production mode.")
            if len(self.orion_demo_key.strip()) < 32:
                raise ValueError("ORION_DEMO_KEY must be at least 32 characters in production mode.")
            if not self.nebius_api_key or not self.nebius_api_key.strip():
                raise ValueError("NEBIUS_API_KEY must be set in production mode.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
