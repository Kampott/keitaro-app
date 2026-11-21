import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import campaigns, config, flows, geo, keitaro
from app.api.deps import require_auth
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.database import get_engine
from app.services import upload_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings()  # fail-closed: без настроенной авторизации production не стартует
    # Зависшие uploading после перезапуска переводим в error. Best-effort:
    # недоступность БД не должна мешать старту (в тестах БД намеренно недоступна).
    try:
        with Session(get_engine()) as session:
            upload_service.recover_stale_uploads(session)
    except Exception:
        pass
    yield


dev = os.environ.get("APP_ENV") == "development"
app = FastAPI(
    title="Adrobot",
    lifespan=lifespan,
    docs_url="/docs" if dev else None,
    redoc_url=None,
    openapi_url="/openapi.json" if dev else None,
)


@app.exception_handler(AppError)
def app_error_handler(_, e: AppError):
    body = {"code": e.code, "message": e.message}
    if e.details is not None:
        body["details"] = e.details
    return JSONResponse(body, status_code=e.status, headers=e.headers)


@app.get("/healthz")
def healthz():
    s = get_settings()
    try:
        with get_engine().connect() as c:
            c.execute(text("select 1"))
        db = True
    except Exception:
        db = False
    return {"status": "ok", "db": db, "keitaro_configured": bool(s.keitaro_base_url and s.keitaro_api_key)}


api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])
api.include_router(config.router)
api.include_router(geo.router)
api.include_router(keitaro.router)
api.include_router(campaigns.router)
api.include_router(flows.router)
app.include_router(api)
