import httpx
import respx

from app.services.keitaro_client import KeitaroClient
from scripts.keitaro_discovery import STATUS, redact, run

SECRET_URL = "https://secret.example/offer?sub=123"
CAMPAIGNS = [{"id": i, "alias": f"a{i}", "name": f"c{i}", "state": "active", "token": "SECRET-TOKEN"} for i in (1, 2, 3)]
STREAMS = {
    1: [
        {"id": 10, "schema": "redirect", "action_type": "http", "action_options": {"url": SECRET_URL}},
        {"id": 11, "schema": "landings", "action_type": "http", "offers": [{"offer_id": 5, "share": 100, "state": "active"}]},
    ]
}
REF = {
    "streams_actions": [{"key": "http", "field": "url"}],
    "stream_schemas": [{"key": k} for k in ("landings", "redirect", "action")],
    "stream_types": [{"key": "regular"}],
    "stream_filters": [{"value": "country", "modes": ["accept", "reject"]}],
    "domains": [{"id": 1, "name": "t.example", "is_ssl": True, "state": "active"}],
    "groups": [{"id": 1, "name": "g"}],
    "traffic_sources": [{"id": 1, "name": "s"}],
    "offers": [{"id": 5, "name": "o", "state": "active", "action_payload": SECRET_URL}],
    "offers/5": {"id": 5, "name": "o", "action_payload": SECRET_URL},
}


def fake_keitaro(request):
    path, q = request.url.path.removeprefix("/admin_api/v1/"), request.url.params
    if path == "campaigns":
        items = [c for c in CAMPAIGNS if "alias" not in q or c["alias"] == q["alias"]]  # поиск работает только по alias
        off, lim = int(q.get("offset", 0)), int(q.get("limit", 100))
        return httpx.Response(200, json=items[off : off + lim])
    if path.startswith("campaigns/") and path.endswith("/streams"):
        return httpx.Response(200, json=STREAMS.get(int(path.split("/")[1]), []))
    if path.startswith("campaigns/"):
        return httpx.Response(200, json=CAMPAIGNS[int(path.split("/")[1]) - 1])
    if path.startswith("streams/"):
        return httpx.Response(200, json=next(s for ss in STREAMS.values() for s in ss if s["id"] == int(path.split("/")[1])))
    return httpx.Response(200, json=REF[path]) if path in REF else httpx.Response(404, json={})


def test_redact_hides_token_and_urls_but_keeps_keys():
    out = redact({"token": "T", "name": "n", "action_options": {"url": "https://x", "n": 1}, "action_payload": "https://y", "offers": [{"action_payload": ""}]})
    assert out == {"token": "REDACTED", "name": "n", "action_options": {"url": "REDACTED", "n": 1}, "action_payload": "REDACTED", "offers": [{"action_payload": ""}]}


def test_run_writes_report_and_fixtures_without_secrets(tmp_path):
    with respx.mock(base_url="https://k.example/admin_api/v1") as m:
        m.route().mock(side_effect=fake_keitaro)
        run(KeitaroClient("https://k.example", "KEY123"), tmp_path / "fx", tmp_path / "doc.md", scan=5)
    doc = (tmp_path / "doc.md").read_text(encoding="utf-8")
    for n, title in ((2, "Фильтр country, режим accept"), (3, "Куда класть URL редиректа"), (4, "action_type у потока schema=landings"),
                     (7, "GET /campaigns: limit, offset, поиск"), (10, "Поля домена, domain_id в кампании"), (11, "GET /offers")):
        assert f"| {n} | {title} | {STATUS['ok']} |" in doc
    assert "ключи action_options: `url`" in doc and "поиск на стороне Keitaro: `alias`" in doc
    assert (tmp_path / "fx" / "stream_redirect_example.json").exists() and (tmp_path / "fx" / "offers.json").exists()
    for f in [*tmp_path.rglob("*.json"), tmp_path / "doc.md"]:
        text = f.read_text(encoding="utf-8")
        assert not any(s in text for s in ("SECRET-TOKEN", "secret.example", "KEY123")), f.name
    assert '"url": "REDACTED"' in (tmp_path / "fx" / "stream_redirect_example.json").read_text(encoding="utf-8")


def test_run_survives_missing_endpoints(tmp_path):
    def only_campaigns(request):
        return httpx.Response(200, json=[]) if request.url.path.endswith("/campaigns") else httpx.Response(404, json={})

    with respx.mock(base_url="https://k.example/admin_api/v1") as m:
        m.route().mock(side_effect=only_campaigns)
        run(KeitaroClient("https://k.example", "KEY123"), tmp_path / "fx", tmp_path / "doc.md", scan=5)
    doc = (tmp_path / "doc.md").read_text(encoding="utf-8")
    assert STATUS["check"] in doc and STATUS["manual"] in doc
