from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / '.env', extra='ignore')
    app_origin: str = 'http://127.0.0.1:8000'
    cookie_secure: bool = True
    database_url: SecretStr = SecretStr('')
    supabase_url: str = ''
    supabase_publishable_key: SecretStr = SecretStr('')
    supabase_secret_key: SecretStr = SecretStr('')
    google_application_credentials: str = ''
    google_spreadsheet_id: str = ''
    gemini_api_key: SecretStr = SecretStr('')
    gemini_model: str = ''
    auto_import_on_startup: bool = True
    reference_ttl_hours: int = Field(default=24, ge=1, le=168)
    worker_enabled: bool = True
    storage_bucket: str = 'invoice-originals'

    @field_validator('app_origin')
    @classmethod
    def origin_only(cls, value):
        p = urlsplit(value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.path not in ('', '/') or p.query or p.fragment or p.username:
            raise ValueError('APP_ORIGIN must be an HTTP(S) origin without a path')
        return value.rstrip('/')

    @model_validator(mode='after')
    def secure_remote(self):
        p = urlsplit(self.app_origin)
        if p.hostname not in ('localhost', '127.0.0.1', '::1') and (p.scheme != 'https' or not self.cookie_secure):
            raise ValueError('Remote deployments require HTTPS and COOKIE_SECURE=true')
        return self

    def configured(self):
        return {
            'database': bool(self.database_url.get_secret_value()),
            'authentication': bool(self.supabase_url and self.supabase_publishable_key.get_secret_value()),
            'sheets': bool(self.google_application_credentials and self.google_spreadsheet_id),
            'gemini': bool(self.gemini_api_key.get_secret_value() and self.gemini_model),
        }


@lru_cache
def get_settings():
    return Settings()

