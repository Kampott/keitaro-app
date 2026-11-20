"""Список кампаний Keitaro для выбора в Edit Campaign (ТЗ §4.2)."""
import threading
import time

from app.core.errors import AppError
from app.schemas.catalog import KeitaroCampaignItem
from app.services.keitaro_client import KeitaroClient

CACHE_TTL = 30.0  # секунд; список кампаний нужен только для выбора в UI
_lock = threading.Lock()
_cached_at: float = 0.0
_cached: tuple[KeitaroCampaignItem, ...] = ()


def invalidate_cache() -> None:
    """Сбросить кэш (используется тестами и при явном обновлении списка)."""
    global _cached_at, _cached
    with _lock:
        _cached_at = 0.0
        _cached = ()


def _load(client: KeitaroClient) -> tuple[KeitaroCampaignItem, ...]:
    """Один запрос к Keitaro на TTL; поиск и пагинация применяются к кэшу."""
    global _cached_at, _cached
    now = time.monotonic()
    with _lock:
        if _cached and now - _cached_at < CACHE_TTL:
            return _cached

    data = client.request("GET", "campaigns", params={"limit": 1000})
    if not isinstance(data, list):
        raise AppError("KEITARO_BAD_RESPONSE", "Keitaro вернул не список кампаний", 502)

    result: list[KeitaroCampaignItem] = []
    for row in data:
        if not isinstance(row, dict) or row.get("id") is None or row.get("name") is None:
            continue
        state = str(row.get("state") or "active")
        if state == "deleted":
            continue
        try:
            result.append(KeitaroCampaignItem(
                id=int(row["id"]),
                name=str(row["name"]),
                alias=str(row.get("alias") or ""),
                state=state,
            ))
        except (TypeError, ValueError):
            continue

    with _lock:
        _cached = tuple(result)
        _cached_at = time.monotonic()
    return _cached


def list_remote(
    client: KeitaroClient,
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    refresh: bool = False,
) -> list[KeitaroCampaignItem]:
    """Кампании для Editor; Keitaro не ищет по name/alias — фильтруем сами.

    token и прочие служебные поля ответа Keitaro наружу не попадают. Копируем
    модели из кэша, чтобы вызывающий код не мог изменить общее состояние.
    """
    if refresh:
        invalidate_cache()
    rows = _load(client)
    q = (search or "").strip().lower()
    result = [
        item for item in rows
        if not q or q in item.name.lower() or q in item.alias.lower() or q in str(item.id)
    ]
    return [item.model_copy() for item in result[offset:offset + limit]]
