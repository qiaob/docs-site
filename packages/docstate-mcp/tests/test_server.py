"""Tools and resources of the standalone server, end to end through the HTTP API."""

import json

import pytest
from fastmcp.exceptions import ToolError


def _data(result):
    data = getattr(result, "data", None)
    if data is not None:
        return data
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and set(structured) == {"result"}:
        return structured["result"]
    if structured:
        return structured
    return json.loads(result.content[0].text)


async def test_tools_and_resources_are_listed(mcp):
    names = {t.name for t in await mcp.list_tools()}
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
    templates = {t.uriTemplate for t in await mcp.list_resource_templates()}
    assert "docs://{slug}" in templates and "docs://{slug}/v/{version}" in templates


async def test_publish_read_and_archive(mcp):
    first = _data(
        await mcp.call_tool(
            "docs_publish",
            {
                "title": "Agent doc",
                "category": "agents/reports",
                "content": "# one\n\nhello",
                "slug": "agent-doc",
                "tags": ["a"],
            },
        )
    )
    assert first["outcome"] == "created" and first["url"] == "http://testserver/d/agent-doc"
    second = _data(
        await mcp.call_tool(
            "docs_publish",
            {
                "title": "Agent doc",
                "category": "agents/reports",
                "content": "# two",
                "slug": "agent-doc",
                "label": "v2",
            },
        )
    )
    assert second["outcome"] == "new_version" and second["version"] == 2

    got = _data(
        await mcp.call_tool(
            "docs_get", {"slug": "agent-doc", "version": 1, "include_content": True}
        )
    )
    assert got["version"]["content"] == "# one\n\nhello" and got["tags"] == ["a"]
    assert got["created_by"] == "agent@example.com"  # the author the server was started with

    versions = _data(await mcp.call_tool("docs_versions", {"slug": "agent-doc"}))
    assert [v["no"] for v in versions] == [2, 1]
    listed = _data(await mcp.call_tool("docs_list", {"category": "agents"}))
    assert listed[0]["slug"] == "agent-doc"
    assert _data(await mcp.call_tool("docs_search", {"q": "two"}))[0]["slug"] == "agent-doc"
    tree = _data(await mcp.call_tool("docs_categories", {}))
    assert tree[0]["path"] == "agents" and tree[0]["children"][0]["path"] == "agents/reports"

    latest = await mcp.read_resource("docs://agent-doc")
    assert latest[0].text == "# two"
    v1 = await mcp.read_resource("docs://agent-doc/v/1")
    assert v1[0].text == "# one\n\nhello"

    meta = _data(
        await mcp.call_tool("docs_update_meta", {"slug": "agent-doc", "status": "approved"})
    )
    assert meta["status"] == "approved"
    gone = _data(await mcp.call_tool("docs_archive", {"slug": "agent-doc"}))
    assert gone["outcome"] == "archived"


async def test_check_and_path_publishing(mcp):
    checked = _data(
        await mcp.call_tool("docs_check", {"content": "[x](nope.md) ![i](a.png)", "kind": "md"})
    )
    assert len(checked["warnings"]) == 2
    out = _data(
        await mcp.call_tool(
            "docs_publish", {"title": "From file", "category": "demo", "path": "sample.html"}
        )
    )
    assert out["outcome"] == "created"
    got = _data(await mcp.call_tool("docs_get", {"slug": out["slug"], "include_content": True}))
    assert got["kind"] == "html" and "<h2>" in got["version"]["content"]
    assert got["version"]["source_path"] == "sample.html"
    with pytest.raises(ToolError):
        await mcp.call_tool(
            "docs_publish", {"title": "x", "category": "demo", "path": "../../etc/passwd"}
        )
    with pytest.raises(ToolError):
        await mcp.call_tool(
            "docs_publish", {"title": "x", "category": "demo"}
        )  # neither content nor path
