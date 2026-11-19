import pytest

from app.api.deps import get_keitaro
from app.core.config import get_settings
from app.db.database import get_engine


def _reset():
    for f in (get_settings, get_keitaro, get_engine):
        f.cache_clear()


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_BASIC_AUTH_USER", "u")
    monkeypatch.setenv("APP_BASIC_AUTH_PASSWORD", "p")
    monkeypatch.setenv("KEITARO_BASE_URL", "https://k.example/")
    monkeypatch.setenv("KEITARO_API_KEY", "KEY123")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")  # заведомо недоступна
    _reset()
    yield
    _reset()
