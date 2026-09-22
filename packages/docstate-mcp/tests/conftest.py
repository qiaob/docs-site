"""The standalone MCP server against a real Docstate site running in-process.
Environment defaults match the site's own tests so both suites can share one
pytest process."""

import os
import pathlib

FIXTURES = pathlib.Path(__file__).parents[2] / "docstate" / "tests" / "fixtures"

os.environ.setdefault("DOCSTATE_STORAGE_URL", "sqlite:////tmp/docstate-mcp-test.db")
os.environ["DOCSTATE_CONFIG"] = "/nonexistent/docstate.toml"
os.environ.setdefault("DOCSTATE_AUTH_MODE", "fake")
os.environ.setdefault("DOCSTATE_BASE_URL", "http://testserver")
os.environ.setdefault("DOCSTATE_ALLOWED_DOMAINS", "example.com")

import httpx
import pytest
from fastmcp import Client

from docstate.server.app import app
from docstate.server.deps import get_storage
from docstate_mcp.client import DocstateClient
from docstate_mcp.server import build_server


@pytest.fixture(autouse=True)
def _clean_storage():
    get_storage().clear()
    yield


@pytest.fixture
async def site_client():
    c = DocstateClient(
        "http://testserver", author="agent@example.com", transport=httpx.ASGITransport(app=app)
    )
    yield c
    await c.aclose()


@pytest.fixture
async def mcp(site_client):
    server = build_server(site_client, source_root=FIXTURES)
    async with Client(server) as client:
        yield client
