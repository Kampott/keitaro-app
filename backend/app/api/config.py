"""Признаки режима приложения, которые нужны frontend."""
from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["config"])


@router.get("/config")
def config():
    """Только рабочий флаг: без секретов и без полного имени окружения."""
    return {"allow_arbitrary_offer_ids": get_settings().allow_arbitrary_offer_ids}
