"""The in-process MCP mount, through the real Streamable HTTP endpoint. (The
standalone server has its own tests in packages/docstate-mcp.)"""

import json

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _parse(resp):
    body = resp.text
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        for line in body.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise AssertionError(f"no data frame in SSE body: {body[:200]}")
    return resp.json()


class Mcp:
    def __init__(self, client):
        self.client = client
        self.n = 0
        init = self.call(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        )
        self.sid = init["_session"]
        self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={**HEADERS, "Mcp-Session-Id": self.sid},
        )

    def call(self, method, params=None):
        self.n += 1
        headers = dict(HEADERS)
        if getattr(self, "sid", None):
            headers["Mcp-Session-Id"] = self.sid
        r = self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        out = _parse(r)
        assert "error" not in out, out
        result = out["result"]
        if method == "initialize":
            result["_session"] = r.headers.get("mcp-session-id")
        return result

    def tool(self, name, **arguments):
        result = self.call("tools/call", {"name": name, "arguments": arguments})
        assert not result.get("isError"), result
        structured = result.get("structuredContent")
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]  # non-object returns are wrapped by FastMCP
        return structured or json.loads(result["content"][0]["text"])


def test_tools_listed(client):
    mcp = Mcp(client)
    names = {t["name"] for t in mcp.call("tools/list")["tools"]}
    assert {
        "docs_publish",
        "docs_check",
        "docs_list",
        "docs_search",
        "docs_get",
        "docs_versions",
        "docs_categories",
        "docs_update_meta",
        "docs_archive",
    } <= names


def test_publish_get_versions_roundtrip(client):
    mcp = Mcp(client)
    first = mcp.tool(
        "docs_publish",
        title="MCP 文档",
        category="demo",
        kind="md",
        slug="mcp-doc",
        content="# one",
        tags=["t"],
    )
    assert first["outcome"] == "created" and first["url"] == "http://testserver/d/mcp-doc"
    second = mcp.tool(
        "docs_publish",
        title="MCP 文档",
        category="demo",
        slug="mcp-doc",
        content="# two",
        label="v2",
    )
    assert second["outcome"] == "new_version" and second["version"] == 2

    got = mcp.tool("docs_get", slug="mcp-doc", version=1, include_content=True)
    assert got["version"]["content"] == "# one" and got["tags"] == ["t"]

    versions = mcp.tool("docs_versions", slug="mcp-doc")
    assert [v["no"] for v in versions] == [2, 1] and versions[0]["label"] == "v2"

    listed = mcp.tool("docs_list", category="demo")
    assert listed[0]["slug"] == "mcp-doc"
    assert mcp.tool("docs_search", q="two")[0]["slug"] == "mcp-doc"
    assert mcp.tool("docs_categories")[0]["path"] == "demo"

    meta = mcp.tool("docs_update_meta", slug="mcp-doc", status="approved", tags=["x", "y"])
    assert meta["status"] == "approved" and meta["tags"] == ["x", "y"]

    checked = mcp.tool("docs_check", content="[x](nope.md)", kind="md")
    assert any("nope.md" in w for w in checked["warnings"])

    gone = mcp.tool("docs_archive", slug="mcp-doc")
    assert gone["outcome"] == "archived"


def test_publish_from_source_path(client):
    mcp = Mcp(client)
    out = mcp.tool("docs_publish", title="来自文件", category="demo", path="sample.html")
    assert out["outcome"] == "created"
    assert client.get(f"/raw/{out['slug']}/1").status_code == 200
    got = mcp.tool("docs_get", slug=out["slug"], include_content=True)
    assert got["kind"] == "html" and "<h2>" in got["version"]["content"]


def test_path_outside_source_root_is_refused(client):
    mcp = Mcp(client)
    result = mcp.call(
        "tools/call",
        {
            "name": "docs_publish",
            "arguments": {"title": "x", "category": "demo", "path": "../../etc/passwd"},
        },
    )
    assert result.get("isError") is True
