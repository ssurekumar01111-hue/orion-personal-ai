from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "Orion"
    app_version: str = "0.1.0"
    environment: str = "development"

    nebius_api_key: str
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    nebius_model: str = "nvidia/nemotron-3-super-120b-a12b"

    # Hermes Agent (NemoClaw/OpenShell sandbox) settings.
    # hermes_gateway_token is injected via .env (never committed).
    # Defaults to empty string so the app starts without it; HermesProvider
    # raises a clear error at request time if the token is missing.
    hermes_gateway_token: str = ""
    hermes_base_url: str = "http://127.0.0.1:8642/v1"
    hermes_model: str = "hermes-agent"

    model_timeout_seconds: float = 60.0

    model_config = SettingsConfigDict(
        env_file=(_ENV_FILE, ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )




@lru_cache
def get_settings() -> Settings:
    return Settings()
