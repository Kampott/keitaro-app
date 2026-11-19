from fastapi import APIRouter, Depends

from app.api.deps import get_keitaro
from app.core.errors import AppError
from app.services.keitaro_client import KeitaroClient

router = APIRouter(prefix="/keitaro")


@router.get("/ping")
def ping(keitaro: KeitaroClient = Depends(get_keitaro)):
    """Проверка URL и ключа: наружу идёт только счётчик, сырой ответ Keitaro (там есть token) не отдаём."""
    campaigns = keitaro.request("GET", "campaigns", params={"limit": 1})
    if not isinstance(campaigns, list):
        raise AppError("KEITARO_BAD_RESPONSE", "Неожиданная форма ответа Keitaro", 502)
    return {"ok": True, "campaigns_returned": len(campaigns)}
