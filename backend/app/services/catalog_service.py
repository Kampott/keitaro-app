"""Справочники Keitaro и статический список стран (ТЗ §3.2, §6)."""
import json
import threading
import time
from functools import lru_cache
from pathlib import Path

from app.core.errors import AppError
from app.schemas.catalog import Country, DomainItem, OfferItem, ReferenceItem
from app.services.keitaro_client import KeitaroClient

OFFERS_TTL = 60.0
MAX_OFFERS = 20
_COUNTRIES_PATH = Path(__file__).resolve().parents[1] / "core" / "countries.json"


@lru_cache
def get_countries() -> tuple[Country, ...]:
    """Единый источник кодов ISO 3166-1 alpha-2 для /api/geo и валидации."""
    data = json.loads(_COUNTRIES_PATH.read_text(encoding="utf-8"))
    return tuple(Country(code=row["code"], name=row["name"]) for row in data)


@lru_cache
def country_codes() -> frozenset[str]:
    return frozenset(c.code for c in get_countries())


class CatalogService:
    """Тонкая обёртка над справочниками Keitaro. Ключ и сырые поля наружу не отдаём."""

    def __init__(self, client: KeitaroClient):
        self._client = client
        self._offers: list | None = None
        self._offers_at = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _as_list(data, path: str) -> list:
        if not isinstance(data, list):
            raise AppError("KEITARO_BAD_RESPONSE", f"Неожиданная форма ответа Keitaro: {path}", 502)
        return data

    @staticmethod
    def _reference(row) -> ReferenceItem | None:
        if not isinstance(row, dict) or row.get("id") is None or row.get("name") is None:
            return None
        try:
            return ReferenceItem(id=int(row["id"]), name=str(row["name"]))
        except (TypeError, ValueError):
            return None

    def domains(self) -> list[DomainItem]:
        """Только активные домены (§3.2): is_ssl нужен для сборки tracking URL."""
        rows = self._as_list(self._client.request("GET", "domains"), "domains")
        result: list[DomainItem] = []
        for row in rows:
            if not isinstance(row, dict) or row.get("state") != "active":
                continue
            item = self._reference(row)
            if item is not None:
                result.append(DomainItem(id=item.id, name=item.name, is_ssl=bool(row.get("is_ssl"))))
        return result

    def groups(self) -> list[ReferenceItem]:
        rows = self._as_list(
            self._client.request("GET", "groups", params={"type": "campaigns"}), "groups"
        )
        return [x for x in (self._reference(r) for r in rows) if x is not None]

    def sources(self) -> list[ReferenceItem]:
        rows = self._as_list(self._client.request("GET", "traffic_sources"), "traffic_sources")
        return [x for x in (self._reference(r) for r in rows) if x is not None]

    def create_group(self, name: str) -> ReferenceItem:
        """D4: POST /groups с {name, type: 'campaigns'}, position назначает Keitaro."""
        data = self._client.request("POST", "groups", json={"name": name, "type": "campaigns"})
        row = data[0] if isinstance(data, list) and data else data
        if isinstance(row, dict) and row.get("id") is not None:
            try:
                return ReferenceItem(id=int(row["id"]), name=str(row.get("name") or name))
            except (TypeError, ValueError):
                pass
        raise AppError("KEITARO_BAD_RESPONSE", "Не удалось создать группу: неожиданный ответ Keitaro", 502)

    def _cached_offers(self) -> list:
        """Полный GET /offers кэшируется на 60 секунд; Keitaro не фильтрует на своей стороне."""
        now = time.monotonic()
        with self._lock:
            if self._offers is not None and now - self._offers_at < OFFERS_TTL:
                return self._offers
        data = self._as_list(self._client.request("GET", "offers"), "offers")
        with self._lock:
            self._offers = data
            self._offers_at = time.monotonic()
        return data

    def find_offer(self, offer_id: int) -> OfferItem | None:
        """Проверка существования активного оффера при валидации Creator (без лимита подсказок)."""
        for row in self._cached_offers():
            if not isinstance(row, dict) or row.get("state") != "active":
                continue
            if str(row.get("id")) != str(offer_id):
                continue
            try:
                return OfferItem(id=int(row["id"]), name=str(row["name"]))
            except (TypeError, ValueError, KeyError):
                return None
        return None

    def get_offer(self, offer_id: int) -> OfferItem | None:
        """§4.4: сначала кэш, при промахе — GET /offers/{id}; только активные офферы."""
        cached = self.find_offer(offer_id)
        if cached is not None:
            return cached
        try:
            data = self._client.request("GET", f"offers/{offer_id}")
        except AppError as e:
            if e.code == "KEITARO_NOT_FOUND":
                return None
            raise
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict) or data.get("state") != "active":
            return None
        try:
            if int(data["id"]) != offer_id:
                return None
            return OfferItem(id=offer_id, name=str(data["name"]))
        except (KeyError, TypeError, ValueError):
            return None

    def invalidate_offers(self) -> None:
        with self._lock:
            self._offers = None
            self._offers_at = 0.0

    def refresh_offers(self) -> list[dict]:
        """§4.8 п.2: обновить кэш офферов перед Fetch; ошибка Keitaro не даёт пустой список."""
        self.invalidate_offers()
        return [row for row in self._cached_offers() if isinstance(row, dict)]

    def search_offers(self, search: str = "", limit: int = MAX_OFFERS) -> list[OfferItem]:
        """Только state=active, поиск по подстроке имени или по ID, не более 20 результатов."""
        q = (search or "").strip().lower()
        cap = max(1, min(int(limit), MAX_OFFERS))
        result: list[OfferItem] = []
        for row in self._cached_offers():
            if not isinstance(row, dict) or row.get("state") != "active":
                continue
            oid, name = row.get("id"), row.get("name")
            if oid is None or name is None:
                continue
            name_s = str(name)
            if q and q not in name_s.lower() and q not in str(oid):
                continue
            try:
                result.append(OfferItem(id=int(oid), name=name_s))
            except (TypeError, ValueError):
                continue
            if len(result) >= cap:
                break
        return result
