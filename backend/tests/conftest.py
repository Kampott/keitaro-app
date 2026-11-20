import os
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.api.deps import get_catalog, get_keitaro
from app.core.config import get_settings
from app.db import models  # noqa: F401 — регистрация моделей в Base.metadata
from app.db.database import Base, get_engine


def _load_env_file():
    """Тесты читают .env из корня проекта; уже заданные переменные не перетираем."""
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file()


def _reset():
    for f in (get_settings, get_keitaro, get_catalog, get_engine):
        f.cache_clear()


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_BASIC_AUTH_USER", "u")
    monkeypatch.setenv("APP_BASIC_AUTH_PASSWORD", "p")
    monkeypatch.setenv("KEITARO_BASE_URL", "https://k.example/")
    monkeypatch.setenv("KEITARO_API_KEY", "KEY123")
    monkeypatch.setenv("KEITARO_DEFAULT_DOMAIN_ID", "1813")
    monkeypatch.setenv("KEITARO_DEFAULT_GROUP_ID", "10489")
    monkeypatch.setenv("KEITARO_DEFAULT_TRAFFIC_SOURCE_ID", "836")
    monkeypatch.setenv("GOOGLE_REDIRECT_URL", "https://google.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")  # заведомо недоступна
    _reset()
    yield
    _reset()


def _test_database_url() -> str:
    """Отдельная тестовая БД PostgreSQL: <DATABASE_URL>_test или TEST_DATABASE_URL."""
    explicit = os.environ.get("TEST_DATABASE_URL", "").strip()
    url = explicit or os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("Нужен TEST_DATABASE_URL или DATABASE_URL (PostgreSQL)")
    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    if not name:
        pytest.skip("DATABASE_URL без имени базы")
    if not explicit:
        name = name if name.endswith("_test") else f"{name}_test"
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        pytest.fail("Некорректное имя тестовой БД")
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, ""))


@pytest.fixture(scope="session")
def pg_engine():
    url = _test_database_url()
    parts = urlsplit(url)
    name = parts.path.lstrip("/")

    # БД может не существовать — создаём её от имени того же пользователя.
    admin_url = urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()

    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session(pg_engine):
    """Каждый тест в своей транзакции с SAVEPOINT, откатываемой в конце.

    SAVEPOINT нужен, чтобы IntegrityError внутри теста не разрывал внешнюю
    транзакцию (иначе SQLAlchemy ругается «transaction already deassociated»).
    """
    connection = pg_engine.connect()
    transaction = connection.begin()
    s = Session(connection, join_transaction_mode="create_savepoint")
    try:
        yield s
    finally:
        s.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
