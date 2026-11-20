"""Список кампаний Keitaro для выбора в Edit Campaign (ТЗ §4.2)."""
from app.core.errors import AppError
from app.schemas.catalog import KeitaroCampaignItem
from app.services.keitaro_client import KeitaroClient


def list_remote(
    client: KeitaroClient,
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[KeitaroCampaignItem]:
    """Keitaro не ищет по alias/name (Phase 0 п.7): фильтруем загруженный список сами.

    Наружу отдаём только поля, нужные для выбора; token и прочие служебные поля
    ответа Keitaro наружу не попадают.
    """
    data = client.request("GET", "campaigns", params={"limit": 1000})
    if not isinstance(data, list):
        raise AppError("KEITARO_BAD_RESPONSE", "Keitaro вернул не список кампаний", 502)

    q = (search or "").strip().lower()
    result: list[KeitaroCampaignItem] = []
    for row in data:
        if not isinstance(row, dict) or row.get("id") is None or row.get("name") is None:
            continue
        state = str(row.get("state") or "active")
        if state == "deleted":
            continue
        try:
            item = KeitaroCampaignItem(
                id=int(row["id"]),
                name=str(row["name"]),
                alias=str(row.get("alias") or ""),
                state=state,
            )
        except (TypeError, ValueError):
            continue
        if q and q not in item.name.lower() and q not in item.alias.lower() and q not in str(item.id):
            continue
        result.append(item)

    return result[offset:offset + limit]
