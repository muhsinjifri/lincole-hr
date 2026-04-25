from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    jotform_api_key: str
    jotform_form_id: str
    # Optional: a second form to display alongside the first on the dashboard.
    jotform_form_id_2: str = ""
    # US: https://api.jotform.com/v1 — EU/GDPR accounts often need https://eu-api.jotform.com/v1
    jotform_api_base: str = "https://api.jotform.com/v1"
    # Comma-separated question ids, e.g. "5,12,37". Empty = show all fields present on submissions.
    jotform_field_ids: str = ""
    # Optional: numeric question id for "Department" if auto-detect by label fails.
    jotform_department_field_id: str = ""
    # Optional: numeric question id for a file-upload (resume) field — adds a Resume column with view/download links.
    jotform_resume_field_id: str = ""
    # Optional: numeric question id for a Short Text (or similar) field used for notes (POST /api/submissions/{id}/notes).
    jotform_notes_field_id: str = ""
    # If set, POST /api/submissions/{id}/notes requires Authorization: Bearer ... or ?token=... matching this value.
    notes_api_secret: str = ""
    # If true (default), View/Download use this app as a proxy (API key on server) so you need not log into Jotform in the browser.
    jotform_upload_proxy: bool = True

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
    def resume_field_id(self) -> str | None:
        raw = self.jotform_resume_field_id.strip()
        return raw or None

    @property
    def notes_field_id(self) -> str | None:
        raw = self.jotform_notes_field_id.strip()
        return raw or None

    @property
    def notes_api_token(self) -> str | None:
        raw = self.notes_api_secret.strip()
        return raw or None

    @property
    def use_upload_proxy(self) -> bool:
        return bool(self.jotform_upload_proxy)

    @property
    def form_ids(self) -> list[str]:
        out: list[str] = []
        for raw in (self.jotform_form_id, self.jotform_form_id_2):
            v = (raw or "").strip()
            if v and v not in out:
                out.append(v)
        return out

    @property
    def webhook_token(self) -> str | None:
        raw = self.webhook_secret.strip()
        return raw or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
