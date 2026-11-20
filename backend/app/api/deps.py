import secrets
from functools import lru_cache

from fastapi import Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.database import get_engine
from app.services.catalog_service import CatalogService
from app.services.keitaro_client import KeitaroClient

_basic = HTTPBasic(auto_error=False)


def require_auth(creds: HTTPBasicCredentials | None = Depends(_basic)) -> None:
    s = get_settings()
    if not (s.basic_user and s.basic_password):  # возможно только при APP_ENV=development
        return
    ok = creds is not None
    if ok:  # `&`, а не `and`: оба сравнения выполняются всегда
        ok = secrets.compare_digest(creds.username.encode(), s.basic_user.encode()) & secrets.compare_digest(
            creds.password.encode(), s.basic_password.encode()
        )
    if not ok:
        raise AppError("UNAUTHORIZED", "Нужен логин и пароль", 401, headers={"WWW-Authenticate": "Basic"})


@lru_cache
def get_keitaro() -> KeitaroClient:
    s = get_settings()
    if not (s.keitaro_base_url and s.keitaro_api_key):
        raise AppError("KEITARO_NOT_CONFIGURED", "Задайте KEITARO_BASE_URL и KEITARO_API_KEY в .env", 503)
    return KeitaroClient(s.keitaro_base_url, s.keitaro_api_key)


@lru_cache
def get_catalog() -> CatalogService:
    return CatalogService(get_keitaro())


def get_db():
    """Сессия PostgreSQL; в тестах подменяется через app.dependency_overrides."""
    with Session(get_engine()) as session:
        yield session
