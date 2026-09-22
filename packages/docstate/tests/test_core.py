"""The publishing rules, against the SQLite-backed store the app uses."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from docstate.core import publish as pub
from docstate.core import text
from docstate.core.models import DocQuery, PublishRequest

ALICE = "alice@example.com"
BOB = "bob@example.com"


def test_slug_rules():
    assert text.slugify("Hello World! 2026") == "hello-world-2026"
    assert text.normalize_category(" Algorithm//Reports/ ") == "algorithm/reports"
    assert text.normalize_category("../x") == "x"
    assert text.normalize_category("") == "misc"
    when = dt.datetime(2026, 9, 9, 1, 2)
    assert text.make_slug("Hello", None, when) == "hello"
    # a non-ASCII title falls back to date + random id
    assert text.make_slug("中文标题", None, when).startswith("20260909-")
    assert text.make_slug("中文标题", "ab", when) == "ab"  # explicit slugs are kept


def test_publish_lifecycle(store, publish_md):
    doc, v1, outcome = publish_md()
    assert outcome == "created" and v1.version_no == 1 and doc.latest_version == 1
    assert doc.status == "draft" and doc.summary.startswith("Hello")

    _, v_same, outcome = publish_md()
    assert outcome == "unchanged" and v_same.version_no == 1

    doc, v2, outcome = publish_md(body="# Hello\n\n第二版", label="v2")
    assert outcome == "new_version" and v2.version_no == 2 and v2.label == "v2"
    assert doc.latest_version == 2
    assert [v.version_no for v in store.versions("hello")] == [2, 1]
    assert store.get_version("hello", None).version_no == 2
    assert store.get_version("hello", 1).content.endswith("第一版")
    assert store.get_version("hello", 9) is None


def test_slug_collision_gets_suffix(store):
    a, _, _ = pub.publish(
        store, PublishRequest(title="Readme", content="a", kind="md", category="x", author=ALICE)
    )
    b, _, _ = pub.publish(
        store, PublishRequest(title="Readme", content="b", kind="md", category="y", author=ALICE)
    )
    assert a.slug == "readme" and b.slug == "readme-2"


def test_kind_and_status_validation(store, publish_md):
    with pytest.raises(ValueError):
        publish_md(slug="bad-kind", status="published")
    with pytest.raises(ValueError):
        pub.publish(
            store, PublishRequest(title="t", content="x", kind="pdf", category="c", author=ALICE)
        )


def test_category_tree_and_lists(store, publish_md):
    publish_md(slug="r1", category="algorithm/reports")
    publish_md(slug="r2", category="algorithm/reports")
    publish_md(slug="m1", category="algorithm/models")
    publish_md(slug="s1", category="server")
    tree = pub.category_tree(store)
    by_name = {n["name"]: n for n in tree}
    assert by_name["algorithm"]["count"] == 3
    assert {c["name"]: c["count"] for c in by_name["algorithm"]["children"]} == {
        "reports": 2,
        "models": 1,
    }
    assert [d.slug for d in store.list(DocQuery(category="algorithm"))] == ["m1", "r2", "r1"]
    assert len(store.list(DocQuery(category="algorithm/reports"))) == 2


def test_archive_hides_document(store, publish_md):
    publish_md(slug="gone")
    pub.archive(store, "gone")
    assert store.list(DocQuery()) == []
    assert pub.category_tree(store) == []
    assert store.get("gone").is_archived  # the URL still resolves


def test_timeline_groups_by_local_day(store, publish_md):
    early = dt.datetime(2026, 9, 8, 20, 0)  # 04:00 next day in Asia/Singapore
    late = dt.datetime(2026, 9, 8, 2, 0)  # 10:00 same day in Asia/Singapore
    publish_md(slug="a", created_at=late)
    publish_md(slug="b", created_at=early)
    groups = pub.timeline(store, tz=ZoneInfo("Asia/Singapore"))
    assert [g["day"] for g in groups] == ["2026-09-09", "2026-09-08"]
    assert groups[0]["items"][0]["doc"].slug == "b"


def test_search_matches_body_and_snippet(store, publish_md):
    publish_md(slug="needle", body="# 标题\n\n这里有一段关于缓存命中率的讨论，很长很长。")
    publish_md(slug="other", body="# 无关\n\n别的内容")
    hits = pub.search(store, "缓存命中率")
    assert [h.doc.slug for h in hits] == ["needle"]
    assert "缓存命中率" in hits[0].snippet


def test_wikilink_resolution(store, publish_md):
    publish_md(slug="001-tailscale-overview", title="Tailscale Network Overview")
    assert pub.resolve_wikilink(store, "001-tailscale-overview") == "001-tailscale-overview"
    assert pub.resolve_wikilink(store, "Tailscale Network Overview") == "001-tailscale-overview"
    assert pub.resolve_wikilink(store, "tailscale-overview") == "001-tailscale-overview"
    assert pub.resolve_wikilink(store, "nope") is None


def test_state_scopes_are_isolated(storage, publish_md):
    publish_md()
    state = storage.state
    state.set("hello", "checklist", ALICE, {"0": True}, ALICE)
    state.set("hello", "team", "", {"0": True}, ALICE)
    assert state.get("hello", "checklist", ALICE).value == {"0": True}
    assert state.get("hello", "checklist", BOB) is None
    assert state.get("hello", "team", "").value == {"0": True}
    state.set("hello", "checklist", ALICE, {"0": False}, ALICE)
    assert state.get("hello", "checklist", ALICE).value == {"0": False}


def test_update_meta(store, publish_md):
    publish_md()
    doc = pub.update_meta(store, "hello", title="新标题", tags=["a", "b"], status="approved")
    assert (doc.title, doc.tags, doc.status) == ("新标题", ["a", "b"], "approved")
    assert store.get("hello").tags == ["a", "b"]
    with pytest.raises(ValueError):
        pub.update_meta(store, "hello", status="nope")


def test_publish_ignores_frontmatter_only_differences(store, publish_md):
    publish_md(slug="fm", category="product", body="# FM\n\n正文")
    _, v, outcome = publish_md(slug="fm", body="---\ntitle: FM\ntags: [x]\n---\n\n# FM\n\n正文\n")
    assert outcome == "unchanged" and v.version_no == 1
    _, v, outcome = publish_md(slug="fm", body="---\ntitle: FM\n---\n\n# FM\n\n改了")
    assert outcome == "new_version" and v.version_no == 2
