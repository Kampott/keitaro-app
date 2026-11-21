import os
from dataclasses import dataclass
from functools import lru_cache


def _optional_id(value: str) -> int | None:
    """Пустое значение = None (переменная необязательна). Нечисло = ошибка конфигурации."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(f"Ожидался целочисленный ID, получено: {value!r}") from None


@dataclass(frozen=True)
class Settings:
    app_env: str
    allow_arbitrary_offer_ids: bool
    database_url: str
    keitaro_base_url: str
    keitaro_api_key: str
    basic_user: str
    basic_password: str
    keitaro_default_domain_id: int | None
    keitaro_default_group_id: int | None
    keitaro_default_traffic_source_id: int | None
    google_redirect_url: str


@lru_cache
def get_settings() -> Settings:
    e = os.environ.get
    app_env = e("APP_ENV", "production")
    s = Settings(
        app_env=app_env,
        # Произвольные Offer ID — только для локальной проверки в development.
        allow_arbitrary_offer_ids=app_env == "development",
        database_url=e("DATABASE_URL", ""),
        keitaro_base_url=e("KEITARO_BASE_URL", "").strip().rstrip("/"),
        keitaro_api_key=e("KEITARO_API_KEY", "").strip(),
        basic_user=e("APP_BASIC_AUTH_USER", ""),
        basic_password=e("APP_BASIC_AUTH_PASSWORD", ""),
        keitaro_default_domain_id=_optional_id(e("KEITARO_DEFAULT_DOMAIN_ID", "")),
        keitaro_default_group_id=_optional_id(e("KEITARO_DEFAULT_GROUP_ID", "")),
        keitaro_default_traffic_source_id=_optional_id(e("KEITARO_DEFAULT_TRAFFIC_SOURCE_ID", "")),
        google_redirect_url=e("GOOGLE_REDIRECT_URL", "https://google.com").strip() or "https://google.com",
    )
    if not s.database_url:
        raise RuntimeError("DATABASE_URL не задан")
    # fail-closed: открытый режим только при явном APP_ENV=development
    if s.app_env != "development" and not (s.basic_user and s.basic_password):
        raise RuntimeError(
            "Задайте APP_BASIC_AUTH_USER и APP_BASIC_AUTH_PASSWORD "
            "(или APP_ENV=development для локальной разработки)"
        )
    return s
