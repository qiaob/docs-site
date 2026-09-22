"""The document endpoints the MCP server and other services call."""

from docstate.settings import get_settings

BOB = "bob@example.com"


def test_get_versions_update_archive(client, publish_md):
    publish_md(
        slug="g1",
        title="G1",
        category="algorithm/reports",
        body="# G1\n\n第一版",
        source_path="algorithm/reports/g1.md",
    )
    publish_md(slug="g1", body="# G1\n\n第二版", label="v2")
    d = client.get("/api/docs/g1").json()
    assert d["slug"] == "g1" and d["latest_version"] == 2 and d["version"]["no"] == 2
    assert d["url"].endswith("/d/g1") and d["version"]["url"].endswith("/d/g1?v=2")
    assert "content" not in d["version"] and d["archived_at"] is None
    v1 = client.get("/api/docs/g1?version=1&content=1").json()
    assert v1["version"]["no"] == 1 and v1["version"]["content"] == "# G1\n\n第一版"
    assert v1["version"]["source_path"] == "algorithm/reports/g1.md"
    assert client.get("/api/docs/g1?version=9").status_code == 404
    assert client.get("/api/docs/g1?version=x").status_code == 400
    assert client.get("/api/docs/nope").status_code == 404
    vs = client.get("/api/docs/g1/versions").json()
    assert [v["no"] for v in vs] == [2, 1] and vs[0]["label"] == "v2"

    r = client.patch(
        "/api/docs/g1",
        json={
            "title": "G1 改",
            "tags": ["a", "b"],
            "status": "review",
            "category": "algorithm/models",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "G1 改" and body["tags"] == ["a", "b"]
    assert body["status"] == "review" and body["category"] == "algorithm/models"
    assert client.patch("/api/docs/g1", json={"status": "bogus"}).status_code == 400
    assert client.get("/api/docs/g1").json()["latest_version"] == 2  # meta change: no version

    a = client.post("/api/docs/g1/archive")
    assert a.status_code == 200 and a.json()["outcome"] == "archived" and a.json()["archived_at"]
    assert client.post("/api/docs/g1/archive").json()["outcome"] == "already_archived"
    assert not any(x["slug"] == "g1" for x in client.get("/api/docs").json())
    assert client.get("/d/g1").status_code == 200  # the URL keeps answering
    assert client.get("/api/docs/g1").json()["archived_at"]


def test_reads_accept_the_trusted_service_or_the_reader(client, publish_md, monkeypatch):
    publish_md(slug="s1", category="demo", body="# S1\n\n正文")
    monkeypatch.setattr(get_settings(), "api_tokens", "svc:svc")
    svc = {"X-Docstate-Token": "svc", "X-Docstate-Author": BOB}
    assert client.get("/api/docs/s1", headers=svc).status_code == 200
    assert client.get("/api/docs?status=draft", headers=svc).json()[0]["slug"] == "s1"
    assert client.get("/api/docs/s1", headers={"X-Docstate-Token": "nope"}).status_code == 403
    assert client.get("/api/docs/s1").status_code == 200  # the signed-in reader, no token
    # writes need the token once tokens are configured
    assert client.patch("/api/docs/s1", json={"title": "x"}).status_code == 403
    assert client.patch("/api/docs/s1", json={"title": "x"}, headers=svc).status_code == 200
    assert client.post("/api/docs/s1/archive", headers=svc).json()["outcome"] == "archived"


def test_categories_tree(client, publish_md):
    publish_md(slug="c1", category="dw/zh", body="# 1\n\n正文")
    publish_md(slug="c2", category="dw/en", body="# 2\n\n正文")
    publish_md(slug="c3", category="dw", body="# 3\n\n正文")
    tree = client.get("/api/categories").json()
    dw = next(n for n in tree if n["path"] == "dw")
    assert dw["count"] == 3 and dw["name"] == "dw"
    assert {c["path"]: c["count"] for c in dw["children"]} == {"dw/en": 1, "dw/zh": 1}
    assert "docs" not in dw  # the tree carries no documents


def test_publish_dry_run_and_warnings(client, publish_md):
    publish_md(slug="exists", category="demo", body="# E\n\n正文")
    body = {
        "title": "W",
        "kind": "md",
        "category": "demo",
        "slug": "warned",
        "content": "# W\n\n[ok](/d/exists) [bad](/d/nope) [rel](other.md) ![i](img/a.png) [[missing]]",
    }
    r = client.post("/api/publish", json={**body, "dry_run": True})
    assert r.status_code == 200 and r.json()["outcome"] == "dry_run"
    w = r.json()["warnings"]
    assert any("/d/nope" in x for x in w) and any("other.md" in x for x in w)
    assert any("img/a.png" in x for x in w) and any("[[missing]]" in x for x in w)
    assert not any("/d/exists" in x for x in w)
    assert client.get("/api/docs/warned").status_code == 404  # a dry run stores nothing
    real = client.post("/api/publish", json=body).json()
    assert real["outcome"] == "created" and len(real["warnings"]) == 4
    html = {
        "title": "H",
        "kind": "html",
        "category": "demo",
        "slug": "h1",
        "dry_run": True,
        "content": (
            '<div><script src="https://evil.example/x.js"></script>'
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/x/1/x.js"></script>'
            '<img src="pic.png"></div>'
        ),
    }
    w = client.post("/api/publish", json=html).json()["warnings"]
    assert any("<body>" in x for x in w) and any("evil.example" in x for x in w)
    assert any("pic.png" in x for x in w)
    assert not any(x.endswith("x/1/x.js") for x in w)  # the allowed CDN is not flagged
    assert (
        client.post("/api/publish", json={**body, "kind": "pdf", "dry_run": True}).status_code
        == 400
    )
