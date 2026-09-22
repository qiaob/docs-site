"""Bulk import from a repository checkout (what a GitHub Action posts)."""

from pydantic import SecretStr

from docstate.core import importer
from docstate.settings import get_settings

ALICE = "alice@example.com"

MD = """---
title: 开发环境搭建
author: alice
created: 2026-07-24
updated: 2026-07-27
status: draft
tags: [guide, onboarding]
---

# 开发环境搭建

第一段是摘要。
"""
HTML = (
    "<!doctype html><html><head><title>延迟调查报告</title></head><body><p>正文</p></body></html>"
)


def _files(*items):
    return {"ref": "abc1234", "label": "docs(guides): update", "files": list(items)}


def test_import_creates_updates_and_archives(client, store):
    r = client.post(
        "/api/import",
        json=_files(
            {
                "path": "guides/onboarding/20260724-dev-environment-setup.md",
                "content": MD,
                "author": ALICE,
                "committed_at": "2026-09-10T02:00:00Z",
            },
            {
                "path": "reports/20260604-latency-investigation.html",
                "content": HTML,
            },
            {
                "path": ".obsidian/workspace.md",
                "content": "# not a doc, skipped by path rules please",
            },
            {
                "path": "reports/Untitled.md",
                "content": "# skipped by name rule please ignore me",
            },
        ),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"] == {"created": 2, "skipped": 2}
    md = next(x for x in body["results"] if x["path"].endswith(".md"))
    assert md["slug"] == "20260724-dev-environment-setup" and md["version"] == 1
    assert md["url"].endswith("/d/20260724-dev-environment-setup")

    doc = store.get("20260724-dev-environment-setup")
    assert doc.title == "开发环境搭建" and doc.category == "guides/onboarding"
    assert doc.tags == ["guide", "onboarding"] and doc.status == "draft"
    assert doc.created_by == ALICE  # git author beats frontmatter author
    assert doc.summary.startswith("第一段是摘要")
    v = store.get_version(doc.slug, 1)
    assert v.label == "docs(guides): update" and v.created_at.isoformat() == "2026-09-10T02:00:00"
    html_doc = store.get("20260604-latency-investigation")
    assert (
        html_doc.kind == "html"
        and html_doc.title == "延迟调查报告"
        and html_doc.created_by == "repo"
    )

    # same content again -> unchanged; changed content -> new version at the same slug
    again = client.post(
        "/api/import",
        json=_files(
            {
                "path": "guides/onboarding/20260724-dev-environment-setup.md",
                "content": MD,
            }
        ),
    ).json()
    assert again["counts"] == {"unchanged": 1}
    changed = client.post(
        "/api/import",
        json=_files(
            {
                "path": "guides/onboarding/20260724-dev-environment-setup.md",
                "content": MD + "\n\n新的一段。",
                "label": "v2",
            }
        ),
    ).json()
    assert changed["counts"] == {"new_version": 1} and changed["results"][0]["version"] == 2

    # deleted in the repo -> archived, URL still resolves
    gone = client.post(
        "/api/import",
        json=_files(
            {
                "path": "reports/20260604-latency-investigation.html",
                "deleted": True,
            }
        ),
    ).json()
    assert gone["counts"] == {"archived": 1}
    assert client.get("/d/20260604-latency-investigation").status_code == 200
    assert not any(
        d["slug"] == "20260604-latency-investigation" for d in client.get("/api/docs").json()
    )
    missing = client.post(
        "/api/import", json=_files({"path": "nowhere/x.md", "deleted": True})
    ).json()
    assert missing["counts"] == {"missing": 1}


def test_import_slug_collision_uses_parent_dir(client):
    files = _files(
        {
            "path": "dw/en/README.md",
            "content": "# Data warehouse docs (english edition)\n\nintro text here",
        },
        {"path": "dw/zh/README.md", "content": "# 数仓文档（中文版）\n\n这里是简介文字。"},
        {
            "path": "server/api/users/profiles/README.md",
            "content": "# GET Brief Profile\n\nGet a brief profile summary.",
        },
    )
    body = client.post("/api/import", json=files).json()
    slugs = [x["slug"] for x in body["results"]]
    assert slugs == ["en-readme", "zh-readme", "profiles-readme"]
    # re-import maps back to the same documents by path, not by slug guesswork
    again = client.post("/api/import", json=files).json()
    assert again["counts"] == {"unchanged": 3}


def test_import_requires_trusted_service(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "api_tokens", "svc:svc")
    files = _files({"path": "a/b.md", "content": "# Hello world document body text"})
    assert client.post("/api/import", json=files).status_code == 403
    assert (
        client.post("/api/import", json=files, headers={"X-Docstate-Token": "nope"}).status_code
        == 403
    )
    r = client.post("/api/import", json=files, headers={"X-Docstate-Token": "svc"})
    assert r.status_code == 200 and r.json()["counts"] == {"created": 1}
    # a signed-in person through the login proxy is not a trusted service
    monkeypatch.setattr(s, "api_tokens", "")
    monkeypatch.setattr(s, "auth_mode", "header")
    monkeypatch.setattr(s, "auth_header", "X-Forwarded-Email")
    monkeypatch.setattr(s, "auth_proxy_secret", SecretStr("fd"))
    person = {"X-Docstate-Proxy-Secret": "fd", "X-Forwarded-Email": ALICE}
    assert client.post("/api/import", json=files, headers=person).status_code == 403


def test_import_rejects_bad_bodies(client):
    assert (
        client.post(
            "/api/import", content=b"not json", headers={"Content-Type": "application/json"}
        ).status_code
        == 400
    )
    assert client.post("/api/import", json={"files": "x"}).status_code == 400
    r = client.post("/api/import", json=_files({"path": "a/b.md", "content": 12345})).json()
    assert r["counts"] == {"error": 1} and "content must be a string" in r["results"][0]["error"]


def test_importer_path_rules():
    assert importer.wanted("dw/zh/09-claude-mcp.md")
    assert importer.wanted("algorithm/reports/x.html")
    assert not importer.wanted("templates/adr.md")
    assert not importer.wanted("server/x/assets/img.md")
    assert not importer.wanted("notes.txt")
    assert not importer.wanted("dw/Untitled 1.md")
    assert not importer.wanted("CLAUDE.md")
    assert not importer.wanted("server/architecture/recommendation/CLAUDE.md")
    assert not importer.wanted("x/AGENTS.md")
    assert importer.category_of("README.md") == "general"
    assert importer.preferred_slug("decisions/004-storage-ports.md") == "004-storage-ports"
    assert importer.preferred_slug("dw/zh/README.md") == "zh-readme"


def test_import_retires_documents_the_rules_now_exclude(client, monkeypatch):
    files = _files(
        {"path": "notes/keep.md", "content": "# Keep me around please\n\nbody text here"}
    )
    assert client.post("/api/import", json=files).json()["counts"] == {"created": 1}
    monkeypatch.setattr(importer, "SKIP_DIRS", importer.SKIP_DIRS | {"notes"})
    r = client.post("/api/import", json=files).json()
    assert r["counts"] == {"archived": 1} and r["results"][0]["slug"]
    assert client.post("/api/import", json=files).json()["counts"] == {"skipped": 1}
    ai = _files({"path": "CLAUDE.md", "content": "# rules for the assistant, long enough text"})
    assert client.post("/api/import", json=ai).json()["counts"] == {"skipped": 1}


def test_import_refreshes_metadata_and_skips_code_in_summaries(store):
    BOB = "bob@example.com"
    text = "# 指南\n\n```mermaid\ngraph TD\n\n  A --> B\n```\n\n这才是摘要。\n"
    doc, _, outcome = importer.import_file(store, "dw/zh/sum.md", text, author=BOB)
    assert outcome == "created" and doc.summary.startswith("这才是摘要")
    with_meta = "---\ntags: [dw, guide]\nstatus: approved\n---\n" + text
    doc2, v, outcome = importer.import_file(store, "dw/zh/sum.md", with_meta, author=BOB)
    assert doc2.slug == doc.slug and outcome == "unchanged" and v.version_no == 1
    assert doc2.tags == ["dw", "guide"] and doc2.status == "approved"


def test_an_older_body_coming_back_does_not_revert_the_document(store):
    BOB = "bob@example.com"
    importer.import_file(store, "product/e1.md", "# E1\n\n第一版", author=BOB)
    doc, _, _ = importer.import_file(store, "product/e1.md", "# E1\n\n第二版", author=BOB)
    assert doc.latest_version == 2
    # a full re-sync of a repository that still holds the first version
    same, version, outcome = importer.import_file(
        store, "product/e1.md", "# E1\n\n第一版", author=BOB
    )
    assert same.slug == doc.slug and outcome == "unchanged" and version.version_no == 2
