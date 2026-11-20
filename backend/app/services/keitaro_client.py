import httpx

from app.core.errors import AppError

_AUTH_MSG = "Keitaro отклонил запрос: проверьте API key и редакцию Keitaro (Admin API есть не во всех)"


def _message(body) -> str:
    if isinstance(body, dict):
        if "error" in body:
            return str(body["error"])
        parts = [f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}" for k, v in body.items()]
        if parts:
            return "; ".join(parts)
    return "Keitaro отклонил запрос"


class KeitaroClient:
    """Единственная точка входа в Keitaro Admin API. Ключ не попадает ни в ответы, ни в ошибки."""

    def __init__(self, base_url: str, api_key: str):
        self._http = httpx.Client(
            base_url=base_url.rstrip("/") + "/admin_api/v1/",
            headers={"Api-Key": api_key},
            timeout=httpx.Timeout(30, connect=5),
        )

    def request(self, method: str, path: str, *, params=None, json=None, expect_json: bool = True):
        """expect_json=False: любой 2xx = успех, тело не разбираем (DELETE, restore)."""
        attempts = 3 if method == "GET" else 1  # POST/PUT/DELETE не повторяем
        for i in range(attempts):
            last = i == attempts - 1
            try:
                r = self._http.request(method, path.lstrip("/"), params=params, json=json)
            except httpx.TransportError:
                if last:
                    raise AppError("KEITARO_UNREACHABLE", "Keitaro недоступен (сеть или таймаут)", 502) from None
                continue
            if r.status_code >= 500 and not last:
                continue
            return self._parse(r, expect_json=expect_json)

    @staticmethod
    def _parse(r: httpx.Response, *, expect_json: bool = True):
        s = r.status_code
        if s in (401, 402, 403):
            raise AppError("KEITARO_AUTH", _AUTH_MSG, 502)
        if s == 404:
            raise AppError("KEITARO_NOT_FOUND", "Keitaro: объект не найден", 404)
        if s >= 500 or (s >= 400 and s not in (400, 406, 422)):
            raise AppError("KEITARO_BAD_RESPONSE", f"Keitaro вернул ошибку {s}", 502)
        if 200 <= s < 300 and not expect_json:
            return None
        try:
            body = r.json()
        except ValueError:
            raise AppError(
                "KEITARO_BAD_RESPONSE", "Ответ Keitaro не JSON: проверьте KEITARO_BASE_URL (без /admin)", 502
            ) from None
        if s >= 400 or (isinstance(body, dict) and "error" in body):
            raise AppError("KEITARO_VALIDATION", _message(body), 422)
        return body