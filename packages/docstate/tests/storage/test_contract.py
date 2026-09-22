"""One contract, every adapter. A new storage backend passes when this file
passes against it. PostgreSQL joins in when DOCSTATE_TEST_POSTGRES_URL is set
(`make test-pg`)."""

from __future__ import annotations

import datetime as dt
import os

import pytest

from docstate.core import publish as pub
from docstate.core.models import DocQuery, PublishRequest, RepoBinding
from docstate.storage import StorageError, open_storage

ALICE = "alice@example.com"
BOB = "bob@example.com"

BACKENDS = ["memory", "sqlite"]
if os.environ.get("DOCSTATE_TEST_POSTGRES_URL"):
    BACKENDS.append("postgres")


@pytest.fixture(params=BACKENDS)
def storage(request, tmp_path):
    if request.param == "memory":
        s = open_storage("memory://")
    elif request.param == "sqlite":
        s = open_storage(f"sqlite:///{tmp_path}/contract.db")
    else:
        s = open_storage(os.environ["DOCSTATE_TEST_POSTGRES_URL"], table_prefix="contract_")
    s.init()
    s.init()  # idempotent
    if hasattr(s, "clear"):
        s.clear()
    yield s
    s.close()


def _pub(store, slug, body="# Hi\n\ntext", **kw):
    req = dict(
        title=f"Doc {slug}", content=body, kind="md", category="guides/a", author=ALICE, slug=slug
    )
    req.update(kw)
    return pub.publish(store, PublishRequest(**req))


def test_ping_and_describe(storage):
    storage.ping()
    assert "***" in storage.describe() or "@" not in storage.describe()


def test_documents_and_versions(storage):
    store = storage.docs
    doc, v1, outcome = _pub(store, "a")
    assert outcome == "created" and store.get("a") == doc and store.slug_exists("a")
    assert not store.slug_exists("b") and store.get("b") is None
    _, v2, outcome = _pub(store, "a", body="# Hi\n\nmore", label="two")
    assert outcome == "new_version" and v2.version_no == 2
    assert store.get("a").latest_version == 2
    assert [v.version_no for v in store.versions("a")] == [2, 1]
    assert store.get_version("a", None).label == "two"
    assert store.get_version("a", 1).content.endswith("text")
    assert store.get_version("a", 3) is None and store.get_version("zz", 1) is None
    assert store.by_title("Doc a").slug == "a" and store.by_title("nope") is None
    assert store.by_slug_suffix("a").slug == "a"


def test_update_replaces_mutable_fields(storage):
    store = storage.docs
    _pub(store, "u")
    doc = pub.update_meta(store, "u", title="New", tags=["t1"], status="approved", category="X/Y")
    fresh = store.get("u")
    assert fresh.title == "New" and fresh.tags == ["t1"] and fresh.status == "approved"
    assert fresh.category == "x/y" and fresh == doc
    archived = pub.archive(store, "u")
    assert archived.is_archived and store.get("u").is_archived


def test_list_filters_and_order(storage):
    store = storage.docs
    t0 = dt.datetime(2026, 1, 1)
    _pub(store, "one", created_at=t0, tags=["x"], status="approved")
    _pub(store, "two", created_at=t0 + dt.timedelta(days=1), category="guides/b")
    _pub(store, "three", created_at=t0 + dt.timedelta(days=2), category="ops")
    pub.archive(store, "three")
    assert [d.slug for d in store.list(DocQuery())] == ["two", "one"]
    assert [d.slug for d in store.list(DocQuery(category="guides"))] == ["two", "one"]
    assert [d.slug for d in store.list(DocQuery(category="guides/b"))] == ["two"]
    assert [d.slug for d in store.list(DocQuery(tag="x"))] == ["one"]
    assert [d.slug for d in store.list(DocQuery(status="approved"))] == ["one"]
    assert [d.slug for d in store.list(DocQuery(q="doc tw"))] == ["two"]
    assert [d.slug for d in store.list(DocQuery(limit=1))] == ["two"]
    assert [d.slug for d in store.iter_all()] == ["one", "two", "three"]  # archived included


def test_tree_rows_timeline_and_search(storage):
    store = storage.docs
    t0 = dt.datetime(2026, 5, 1, 10)
    _pub(store, "r", created_at=t0, source_path="guides/a/README.md")
    _pub(store, "s", body="# S\n\nneedle in here", created_at=t0 + dt.timedelta(hours=1))
    _pub(store, "s", body="# S\n\nneedle again", created_at=t0 + dt.timedelta(hours=2))
    rows = store.tree_rows()
    assert {(r.slug, r.source_path) for r in rows} == {("r", "guides/a/README.md"), ("s", None)}
    tl = store.timeline(None, 10)
    assert [(e.doc.slug, e.version.version_no) for e in tl] == [("s", 2), ("s", 1), ("r", 1)]
    assert [e.doc.slug for e in store.timeline("guides/a", 1)] == ["s"]
    assert [e.doc.slug for e in store.timeline("ops", 10)] == []
    hits = store.search("needle", 10)
    assert [d.slug for d, _ in hits] == ["s"] and "again" in hits[0][1]
    assert store.search("Doc r", 10)[0][0].slug == "r"  # title match


def test_source_paths_and_repo_bindings(storage):
    store = storage.docs
    _pub(store, "p", source_path="Guides/A/p.md")
    assert store.by_source_path("guides/a/p.md").slug == "p"  # case-insensitive
    assert store.by_source_path("nope.md") is None
    _pub(store, "q")
    assert store.repo_binding("q") is None
    b = RepoBinding(slug="q", path="guides/a/q.md", synced_version=1, pr_state="open", pr_number=7)
    store.save_repo_binding(b)
    got = store.repo_binding("q")
    assert got.path == "guides/a/q.md" and got.synced_version == 1 and got.updated_at is not None
    assert store.by_source_path("guides/a/q.md").slug == "q"  # bound paths resolve too
    got.pr_state = "merged"
    got.last_error = "x"
    store.save_repo_binding(got)
    assert (
        store.repo_binding("q").pr_state == "merged" and store.repo_binding("q").last_error == "x"
    )
    assert [x.slug for x in store.repo_bindings(pr_state="open")] == []
    assert [x.slug for x in store.repo_bindings()] == ["q"]
    with pytest.raises(StorageError):
        store.save_repo_binding(RepoBinding(slug="ghost", path="x"))


def test_state_scopes(storage):
    store, state = storage.docs, storage.state
    _pub(store, "st")
    state.set("st", "k", ALICE, {"a": 1}, ALICE)
    state.set("st", "k", "", [1, 2], BOB)
    assert state.get("st", "k", ALICE).value == {"a": 1}
    assert state.get("st", "k", BOB) is None
    assert state.get("st", "k", "").value == [1, 2] and state.get("st", "k", "").updated_by == BOB
    state.set("st", "k", ALICE, None, ALICE)
    assert state.get("st", "k", ALICE).value is None


def test_transaction_groups_writes(storage):
    store = storage.docs
    if type(storage).__name__ == "MemoryStorage":
        pytest.skip("the memory adapter has no rollback")
    with pytest.raises(RuntimeError):
        with store.transaction():
            _pub(store, "tx")
            assert store.get("tx") is not None  # visible inside the block
            raise RuntimeError("abort")
    assert store.get("tx") is None  # nothing survived the rollback
    with store.transaction():
        _pub(store, "tx2")
    assert store.get("tx2").latest_version == 1
