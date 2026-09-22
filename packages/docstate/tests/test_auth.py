"""header / none / token identity, and the MCP toggle."""

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from docstate import auth
from docstate.server.app import create_app
from docstate.settings import get_settings

ALICE = "alice@example.com"
BOB = "bob@example.com"
SECRET_HDR = {"X-Docstate-Proxy-Secret": "front-door-secret"}


@pytest.fixture
def header_mode(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "header")
    monkeypatch.setattr(s, "auth_header", "X-Forwarded-Email")
    monkeypatch.setattr(s, "auth_proxy_secret", SecretStr("front-door-secret"))
    yield s


def test_header_mode_with_proxy_secret_requires_both(client, header_mode):
    assert client.get("/").status_code == 401
    assert client.get("/", headers={"X-Forwarded-Email": ALICE}).status_code == 401
    assert (
        client.get("/", headers={**SECRET_HDR, "X-Forwarded-Email": "x@gmail.com"}).status_code
        == 401
    )
    wrong = {"X-Docstate-Proxy-Secret": "nope", "X-Forwarded-Email": ALICE}
    assert client.get("/", headers=wrong).status_code == 401
    r = client.get("/", headers={**SECRET_HDR, "X-Forwarded-Email": ALICE})
    assert r.status_code == 200 and "alice" in r.text
    # the demo identity switch is not exposed
    assert client.get("/switch?as=" + BOB).status_code == 404
    # the cookie from fake mode means nothing here
    client.cookies.set("docstate_viewer", ALICE)
    assert client.get("/").status_code == 401
    client.cookies.clear()


def test_header_mode_refuses_to_boot_without_a_header_name(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "header")
    monkeypatch.setattr(s, "auth_header", "")
    with pytest.raises(RuntimeError):
        auth.check_startup(s)


def test_state_api_in_header_mode_uses_forwarded_email(client, publish_md, header_mode):
    publish_md(slug="cm")
    hdr = {**SECRET_HDR, "X-Forwarded-Email": BOB, "X-Requested-With": "docstate"}
    r = client.put("/api/state/cm/k?scope=me", json={"value": 1}, headers=hdr)
    assert r.status_code == 200 and r.json()["updated_by"] == BOB
    # someone else, same secret, does not see Bob's private state
    other = {**SECRET_HDR, "X-Forwarded-Email": ALICE}
    assert client.get("/api/state/cm/k?scope=me", headers=other).json()["value"] is None


def test_anonymous_mode_gives_each_browser_its_own_state(publish_md, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_mode", "none")
    publish_md(slug="anon")
    hdr = {"X-Requested-With": "docstate"}
    with TestClient(create_app()) as a, TestClient(create_app()) as b:
        r = a.get("/")
        assert r.status_code == 200 and "docstate_anon" in r.headers.get("set-cookie", "")
        assert "guest" in r.text
        w = a.put("/api/state/anon/k?scope=me", json={"value": 1}, headers=hdr)
        assert w.status_code == 200 and w.json()["updated_by"].startswith("anon:")
        assert a.get("/api/state/anon/k?scope=me").json()["value"] == 1
        b.get("/")
        assert b.get("/api/state/anon/k?scope=me").json()["value"] is None
        b.put("/api/state/anon/team?scope=shared", json={"value": "x"}, headers=hdr)
        assert a.get("/api/state/anon/team?scope=shared").json()["value"] == "x"
        assert a.get("/switch?as=" + BOB).status_code == 404


def test_publish_api_with_service_token(client, store, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "api_tokens", "svc:svc-secret")
    body = {"title": "S", "kind": "md", "category": "demo", "slug": "svc", "content": "# s"}
    assert client.post("/api/publish", json=body).status_code == 403
    bad = {"X-Docstate-Token": "wrong", "X-Docstate-Author": ALICE}
    assert client.post("/api/publish", json=body, headers=bad).status_code == 403
    # a token without an author publishes as the token's name
    r = client.post("/api/publish", json=body, headers={"X-Docstate-Token": "svc-secret"})
    assert r.status_code == 200 and r.json()["outcome"] == "created"
    assert store.get("svc").created_by == "svc"
    # the bearer form works too, and the forwarded person is the author
    ok = {"Authorization": "Bearer svc-secret", "X-Docstate-Author": ALICE}
    r = client.post("/api/publish", json={**body, "slug": "svc2"}, headers=ok)
    assert r.status_code == 200 and store.get("svc2").created_by == ALICE
    assert (
        client.get("/api/docs?q=S", headers={"X-Docstate-Token": "svc-secret"}).status_code == 200
    )


def test_mcp_endpoint_is_off_unless_enabled(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "mcp", False)
    with TestClient(create_app()) as c:
        assert c.get("/healthz").status_code == 200
        assert c.post("/mcp", json={}).status_code in (404, 405)
