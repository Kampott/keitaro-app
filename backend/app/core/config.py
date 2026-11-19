import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    keitaro_base_url: str
    keitaro_api_key: str
    basic_user: str
    basic_password: str


@lru_cache
def get_settings() -> Settings:
    e = os.environ.get
    s = Settings(
        app_env=e("APP_ENV", "production"),
        database_url=e("DATABASE_URL", ""),
        keitaro_base_url=e("KEITARO_BASE_URL", "").strip().rstrip("/"),
        keitaro_api_key=e("KEITARO_API_KEY", "").strip(),
        basic_user=e("APP_BASIC_AUTH_USER", ""),
        basic_password=e("APP_BASIC_AUTH_PASSWORD", ""),
    )
    if not s.database_url:
        raise RuntimeError("DATABASE_URL не задан")
    # D3, fail-closed: открытый режим только при явном APP_ENV=development
    if s.app_env != "development" and not (s.basic_user and s.basic_password):
        raise RuntimeError(
            "Задайте APP_BASIC_AUTH_USER и APP_BASIC_AUTH_PASSWORD "
            "(или APP_ENV=development для локальной разработки)"
        )
    return s
