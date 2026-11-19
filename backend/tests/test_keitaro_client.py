import httpx
import pytest
import respx

from app.core.errors import AppError
from app.services.keitaro_client import KeitaroClient

BASE = "https://k.example/admin_api/v1"


@pytest.fixture
def client():
    return KeitaroClient("https://k.example/", "KEY123")


@pytest.mark.parametrize(
    "status, body, code",
    [
        (401, {}, "KEITARO_AUTH"),
        (402, {}, "KEITARO_AUTH"),
        (403, {}, "KEITARO_AUTH"),
        (404, {}, "KEITARO_NOT_FOUND"),
        (200, {"error": "boom"}, "KEITARO_VALIDATION"),
        (400, {"error": "boom"}, "KEITARO_VALIDATION"),
        (406, {"name": ["dup"]}, "KEITARO_VALIDATION"),
        (422, {"alias": ["dup"]}, "KEITARO_VALIDATION"),
        (405, {}, "KEITARO_BAD_RESPONSE"),
    ],
)
def test_error_normalization(client, status, body, code):
    with respx.mock(base_url=BASE) as m:
        m.get("campaigns").respond(status, json=body)
        with pytest.raises(AppError) as e:
            client.request("GET", "campaigns")
    assert e.value.code == code
    assert "KEY123" not in e.value.message


def test_field_errors_are_readable(client):
    with respx.mock(base_url=BASE) as m:
        m.post("campaigns").respond(406, json={"name": ["Name is taken"]})
        with pytest.raises(AppError) as e:
            client.request("POST", "campaigns", json={})
    assert e.value.message == "name: Name is taken"


def test_success_and_api_key_header(client):
    with respx.mock(base_url=BASE) as m:
        route = m.get("campaigns").respond(json=[{"id": 1}])
        assert client.request("GET", "campaigns", params={"limit": 1}) == [{"id": 1}]
    assert route.calls[0].request.headers["Api-Key"] == "KEY123"


def test_get_retries_on_5xx_but_post_does_not(client):
    with respx.mock(base_url=BASE) as m:
        get = m.get("campaigns").respond(500)
        post = m.post("campaigns").respond(500)
        with pytest.raises(AppError) as e:
            client.request("GET", "campaigns")
        assert e.value.code == "KEITARO_BAD_RESPONSE" and get.call_count == 3
        with pytest.raises(AppError):
            client.request("POST", "campaigns", json={})
        assert post.call_count == 1


def test_network_error_and_non_json(client):
    with respx.mock(base_url=BASE) as m:
        m.get("campaigns").mock(side_effect=httpx.ConnectError("x"))
        with pytest.raises(AppError) as e:
            client.request("GET", "campaigns")
        assert e.value.code == "KEITARO_UNREACHABLE"
        m.get("domains").respond(200, text="<html>login</html>")
        with pytest.raises(AppError) as e:
            client.request("GET", "domains")
        assert e.value.code == "KEITARO_BAD_RESPONSE" and "KEITARO_BASE_URL" in e.value.message
