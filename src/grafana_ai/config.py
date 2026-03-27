from __future__ import annotations

from typing import Literal

from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    grafana_url: str
    grafana_api_token: SecretStr
    grafana_dashboard_uid: str | None = None
    grafana_timeout_s: float = 30.0

    ai_provider: Literal["openai", "ollama", "none"] = "ollama"

    # OpenAI
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None

    # Ollama (local LLM)
    ollama_url: str | None = "http://127.0.0.1:11434"
    ollama_model: str | None = "llama3"
    ollama_timeout_s: float = 300.0
    ollama_num_predict: int | None = 900

    # Digest limits
    max_panels: int = 200
    max_targets_per_panel: int = 6

    # Datasource time series querying + anomaly detection (via Grafana /api/ds/query)
    enable_timeseries_query: bool = False
    timeseries_max_panels: int = 0  # 0 = all panels
    anomaly_z_threshold: float = 6.0

    # Optional auth for this service (recommended if Grafana will call it)
    service_api_key: SecretStr | None = None

    # Optional token for iframe-based embedding in Grafana built-in Text panel.
    # The Text panel iframe cannot send custom headers, so this uses a query parameter.
    service_embed_token: SecretStr | None = None

    # CORS (for Grafana frontend plugins calling this service directly)
    cors_allow_origins: str | None = None


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = []
        for e in exc.errors():
            if e.get("type") == "missing":
                loc = e.get("loc")
                if isinstance(loc, tuple) and loc:
                    missing.append(str(loc[0]))
        missing_txt = ", ".join(sorted(set(missing))) if missing else "(unknown)"
        raise RuntimeError(
            "Missing required configuration. "
            f"Missing: {missing_txt}. "
            "Create a .env in the project root (or set env vars) with at least GRAFANA_URL and GRAFANA_API_TOKEN. "
            "See .env.example."
        ) from exc

