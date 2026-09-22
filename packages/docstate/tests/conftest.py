"""Test harness: a throwaway SQLite file, fake auth, the real ASGI app with the
MCP endpoint mounted. Environment variables are pinned before the app is
imported because settings are read once at import time."""

import os
import pathlib

_DB = pathlib.Path(os.environ.get("DOCSTATE_TEST_DB_PATH", "/tmp/docstate-test.db"))
for suffix in ("", "-wal", "-shm"):
    p = pathlib.Path(str(_DB) + suffix)
    if p.exists():
        p.unlink()
os.environ["DOCSTATE_STORAGE_URL"] = f"sqlite:///{_DB}"
os.environ["DOCSTATE_CONFIG"] = "/nonexistent/docstate.toml"  # never pick up a local config file
os.environ.setdefault("DOCSTATE_AUTH_MODE", "fake")
os.environ.setdefault("DOCSTATE_MCP", "true")
os.environ.setdefault("DOCSTATE_BASE_URL", "http://testserver")
os.environ.setdefault("DOCSTATE_ALLOWED_DOMAINS", "example.com")
os.environ.setdefault("DOCSTATE_DEMO_VIEWERS", "alice@example.com,bob@example.com")
os.environ.setdefault("DOCSTATE_MCP_SOURCE_ROOT", str(pathlib.Path(__file__).parent / "fixtures"))
os.environ.setdefault("DOCSTATE_TZ", "Asia/Singapore")

import pytest
from starlette.testclient import TestClient

from docstate.core import publish as pub
from docstate.core.models import PublishRequest
from docstate.server.app import app
from docstate.server.deps import get_storage

ALICE = "alice@example.com"
BOB = "bob@example.com"


@pytest.fixture(autouse=True)
def _clean_storage():
    get_storage().clear()
    yield


@pytest.fixture
def storage():
    return get_storage()


@pytest.fixture
def store(storage):
    return storage.docs


@pytest.fixture(scope="session")
def client():
    # The context manager runs the lifespan (FastMCP's session manager needs it).
    with TestClient(app) as c:
        yield c


@pytest.fixture
def as_alice(client):
    client.cookies.set("docstate_viewer", ALICE)
    yield client
    client.cookies.clear()


@pytest.fixture
def publish_md(store):
    def _publish(
        slug="hello",
        title="Hello 文档",
        category="demo",
        body="# Hello\n\n第一版",
        author=ALICE,
        **kw,
    ):
        return pub.publish(
            store,
            PublishRequest(
                title=title,
                content=body,
                kind="md",
                category=category,
                author=author,
                slug=slug,
                **kw,
            ),
        )

    return _publish
