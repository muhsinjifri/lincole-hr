from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    jotform_api_key: str
    jotform_form_id: str
    # US: https://api.jotform.com/v1 — EU/GDPR accounts often need https://eu-api.jotform.com/v1
    jotform_api_base: str = "https://api.jotform.com/v1"
    # Comma-separated question ids, e.g. "5,12,37". Empty = show all fields present on submissions.
    jotform_field_ids: str = ""
    # Optional: numeric question id for "Department" if auto-detect by label fails.
    jotform_department_field_id: str = ""

    # Postgres from docker-compose.yml (default matches compose credentials).
    database_url: str = "postgresql+asyncpg://jotform:jotform@127.0.0.1:5432/jotformdb"

    # If non-empty, POST /webhooks/jotform must include ?token=... matching this value.
    webhook_secret: str = ""

    @property
    def field_id_allowlist(self) -> set[str] | None:
        raw = self.jotform_field_ids.strip()
        if not raw:
            return None
        return {part.strip() for part in raw.split(",") if part.strip()}

    @property
    def api_base(self) -> str:
        return self.jotform_api_base.rstrip("/")

    @property
    def department_field_id(self) -> str | None:
        raw = self.jotform_department_field_id.strip()
        return raw or None

    @property
    def webhook_token(self) -> str | None:
        raw = self.webhook_secret.strip()
        return raw or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
