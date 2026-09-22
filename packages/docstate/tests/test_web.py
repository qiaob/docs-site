from docstate.core import publish as pub
from docstate.core.models import PublishRequest
from docstate.settings import get_settings

ALICE = "alice@example.com"
BOB = "bob@example.com"


def test_pages_render(client, publish_md):
    publish_md(slug="p1", category="algorithm/reports", body="# P1\n\n正文")
    publish_md(slug="p1", body="# P1\n\n正文 v2", label="第二版")
    for path in [
        "/",
        "/c/algorithm/reports",
        "/t",
        "/search?q=正文",
        "/d/p1",
        "/d/p1?v=1",
        "/d/p1/versions",
    ]:
        r = client.get(path)
        assert r.status_code == 200, path
    assert "第二版" in client.get("/d/p1").text
    assert "Back to latest" in client.get("/d/p1?v=1").text
    assert client.get("/d/nope").status_code == 404
    assert client.get("/d/p1?v=7").status_code == 404
    assert "Docstate" in client.get("/").text  # the default site title


def test_raw_is_sandboxed_and_src_downloads(client, publish_md):
    publish_md(slug="r", body="# R\n\nhello")
    r = client.get("/raw/r/1")
    assert r.status_code == 200
    assert r.headers["content-security-policy"].startswith("sandbox ")
    assert "docbridge.js" in r.text and "hello" in r.text
    s = client.get("/src/r/1")
    assert s.headers["content-type"].startswith("text/markdown")
    assert s.headers["content-disposition"] == 'attachment; filename="r-v1.md"'
    assert s.text == "# R\n\nhello"


def test_html_document_passthrough(client, store):
    pub.publish(
        store,
        PublishRequest(
            title="H",
            content="<!doctype html><html><head></head><body><h2>Sec</h2></body></html>",
            kind="html",
            category="demo",
            author=ALICE,
            slug="h",
        ),
    )
    r = client.get("/raw/h/1")
    assert "<h2>Sec</h2>" in r.text and r.text.index("docbridge.js") < r.text.index("</head>")


def test_state_api_scopes_and_csrf(as_alice, publish_md):
    publish_md(slug="st")
    hdr = {"X-Requested-With": "docstate"}
    # write requires the custom header
    assert as_alice.put("/api/state/st/k?scope=me", json={"value": 1}).status_code == 403
    r = as_alice.put("/api/state/st/k?scope=me", json={"value": {"0": True}}, headers=hdr)
    assert r.status_code == 200 and r.json()["updated_by"] == ALICE
    assert as_alice.get("/api/state/st/k?scope=me").json()["value"] == {"0": True}
    # another viewer does not see it
    as_alice.cookies.set("docstate_viewer", BOB)
    assert as_alice.get("/api/state/st/k?scope=me").json()["value"] is None
    # shared scope is visible to everyone
    as_alice.put("/api/state/st/team?scope=shared", json={"value": [1]}, headers=hdr)
    as_alice.cookies.set("docstate_viewer", ALICE)
    assert as_alice.get("/api/state/st/team?scope=shared").json()["value"] == [1]
    assert as_alice.get("/api/state/st/bad key?scope=me").status_code == 400
    assert as_alice.get("/api/state/nope/k").status_code == 404


def test_publish_api_versions(client):
    body = {
        "title": "API 文档",
        "kind": "md",
        "category": "demo",
        "slug": "api-doc",
        "content": "# v1",
    }
    r1 = client.post("/api/publish", json=body, headers={"X-Docstate-Author": ALICE})
    assert r1.json()["outcome"] == "created" and r1.json()["url"] == "http://testserver/d/api-doc"
    r2 = client.post("/api/publish", json={**body, "content": "# v2", "label": "second"})
    assert r2.json()["outcome"] == "new_version" and r2.json()["version"] == 2
    r3 = client.post("/api/publish", json={**body, "content": "# v2"})
    assert r3.json()["outcome"] == "unchanged"
    assert client.post("/api/publish", json={**body, "kind": "pdf"}).status_code == 400
    docs = client.get("/api/docs?q=API").json()
    assert docs[0]["slug"] == "api-doc" and docs[0]["latest_version"] == 2
    hits = client.get("/api/search?q=v2").json()
    assert hits[0]["slug"] == "api-doc" and "v2" in hits[0]["snippet"]
    assert client.get("/api/search").status_code == 400


def test_viewer_switch_and_fake_mode(client):
    r = client.get("/switch?as=" + BOB + "&next=/t", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/t"
    assert "docstate_viewer" in r.headers.get("set-cookie", "")
    # open redirects are refused
    r = client.get("/switch?as=" + BOB + "&next=//evil", follow_redirects=False)
    assert r.headers["location"] == "/"
    # addresses outside the allowed domains are ignored
    r = client.get("/switch?as=x@gmail.com", follow_redirects=False)
    assert "set-cookie" not in r.headers
    client.cookies.clear()


def test_header_auth_mode(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "header")
    monkeypatch.setattr(settings, "auth_header", "X-Forwarded-Email")
    assert client.get("/").status_code == 401
    assert client.get("/", headers={"X-Forwarded-Email": "x@gmail.com"}).status_code == 401
    r = client.get("/", headers={"X-Forwarded-Email": ALICE})
    assert r.status_code == 200 and "alice" in r.text
    assert client.get("/switch?as=" + BOB).status_code == 404
    # the denied page points at the login URL when one is configured
    monkeypatch.setattr(settings, "login_url", "https://sso.example.com/login")
    denied = client.get("/", headers={"Accept": "text/html"})
    assert denied.status_code == 401 and "https://sso.example.com/login" in denied.text


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


def test_readme_is_the_directory_intro(client, publish_md):
    publish_md(
        slug="dw-readme",
        category="dw",
        body="# 数仓指南\n\n[快速上手](zh/01.md) [脚本](../scripts/x.sql)",
        source_path="dw/README.md",
    )
    publish_md(slug="zh-01", category="dw/zh", body="# 01\n\n正文", source_path="dw/zh/01.md")
    publish_md(
        slug="root-readme", category="general", body="# Docs\n\n首页", source_path="README.md"
    )
    page = client.get("/c/dw").text
    assert 'id="readmeframe"' in page and "/raw/dw-readme/1" in page and "All documents" in page
    assert 'id="readmeframe"' not in client.get("/c/dw/zh").text
    assert "/raw/root-readme/1" in client.get("/").text
    assert "/raw/dw-readme/1?embed=1" in page  # the frame asks for the embedded rendering
    raw = client.get("/raw/dw-readme/1").text
    assert 'href="/d/zh-01"' in raw  # repository-relative link -> published document
    assert 'class="eyebrow"' in raw and 'class="doc"' in raw
    embedded = client.get("/raw/dw-readme/1?embed=1").text
    assert 'class="doc embed"' in embedded and 'class="eyebrow"' not in embedded
    assert embedded.count("<script") >= 1  # the bridge is still inlined
    assert 'href="../scripts/x.sql"' in raw  # no DOCSTATE_SOURCE_REPO_URL in tests


def test_sidebar_lists_documents_collapsed_by_default(client, publish_md):
    publish_md(
        slug="dw-readme", category="dw", body="# 数仓指南\n\n入口", source_path="dw/README.md"
    )
    publish_md(
        slug="zh-10",
        title="10 · 十",
        category="dw/zh",
        body="# 10 · 十\n\n正文",
        source_path="dw/zh/10-x.md",
    )
    publish_md(
        slug="zh-02",
        title="2 · 二",
        category="dw/zh",
        body="# 2 · 二\n\n正文",
        source_path="dw/zh/02-x.md",
    )
    publish_md(slug="rep", category="algorithm/reports", body="# 报告\n\n正文")
    home = client.get("/").text
    assert "<details open>" not in home  # everything collapsed on the home page
    assert 'href="/d/zh-02"' in home and 'href="/d/rep"' in home  # every document is in the tree
    assert home.index('href="/d/zh-02"') < home.index(
        'href="/d/zh-10"'
    )  # natural order: 2 before 10
    assert home.index('href="/d/zh-02"') < home.index('href="/d/dw-readme"')  # subdirectories first
    page = client.get("/d/zh-10").text
    assert "<details open>" in page  # dw and dw/zh open on the way to the current document
    assert 'href="/d/zh-10" class="active"' in page
    assert (
        'href="/c/dw/zh" class="active"' not in page
    )  # the document, not its directory, is current
    assert 'id="sidegrip"' in page  # the resize grip


def test_a_link_out_of_a_document_opens_a_real_browser_tab(client, publish_md):
    """A tab opened from the sandboxed frame must not inherit the sandbox, or
    the target site loads with an opaque origin and no session."""
    publish_md(slug="lnk", body="# L\n\n[out](https://example.com)")
    page = client.get("/d/lnk").text
    assert "allow-popups-to-escape-sandbox" in page
    assert "allow-same-origin" not in page  # the document itself stays sandboxed


def test_chinese_ui(client, publish_md, monkeypatch):
    monkeypatch.setattr(get_settings(), "lang", "zh-CN")
    monkeypatch.setattr(get_settings(), "site_title", "团队文档")
    publish_md(slug="zh")
    page = client.get("/").text
    assert "团队文档" in page and "最近更新" in page and 'lang="zh-CN"' in page
    raw = client.get("/raw/zh/1").text
    assert '<html lang="zh-CN">' in raw
