"""Write-back of the site's documents into a git repository, against an
in-memory GitHub."""

from __future__ import annotations

import datetime as dt

import frontmatter

from docstate.core import importer
from docstate.core import publish as pub
from docstate.core.models import Document, PublishRequest
from docstate.integrations.github import repo_sync
from docstate.integrations.github.client import PullRequest, RepoFile
from docstate.settings import get_settings

ALICE = "alice@example.com"
BOB = "bob@example.com"


class FakeGitHub:
    def __init__(
        self, files: dict[str, str] | None = None, *, review_required: tuple[str, ...] = ()
    ):
        self.branches: dict[str, dict[str, str]] = {"main": dict(files or {})}
        self.prs: dict[int, dict] = {}
        self.commits: list[tuple[str, str, str]] = []  # path, author email, message
        self.calls: list[tuple] = []
        self.dispatched: list[tuple[str, str]] = []
        self.review_required = review_required

    def dispatch_workflow(self, workflow, ref, inputs=None):
        self.dispatched.append((workflow, ref))

    def check_access(self):
        return {"full_name": "acme/docs", "permissions": {"push": True}}

    def branch_sha(self, branch):
        self.calls.append(("branch_sha", branch))
        return f"sha-{branch}"

    def create_branch(self, name, sha):
        self.calls.append(("create_branch", name))
        self.branches[name] = dict(self.branches["main"])

    def delete_branch(self, name):
        self.calls.append(("delete_branch", name))
        self.branches.pop(name, None)

    def get_file(self, path, ref):
        self.calls.append(("get_file", path, ref))
        files = self.branches.get(ref, {})
        return RepoFile(sha=f"fsha-{path}", text=files[path]) if path in files else None

    def put_file(self, path, text, *, message, branch, sha=None, author=None):
        self.branches[branch][path] = text
        self.commits.append((path, author["email"], message))
        return "c"

    def delete_file(self, path, *, sha, message, branch, author=None):
        self.branches[branch].pop(path, None)
        self.commits.append((path, author["email"], message))
        return "c"

    def create_pr(self, *, head, base, title, body):
        n = len(self.prs) + 1
        self.prs[n] = {"head": head, "base": base, "title": title, "body": body, "merged": False}
        return PullRequest(number=n, url=f"https://github.com/acme/docs/pull/{n}")

    def merge_pr(self, number, *, method="rebase"):
        pr = self.prs[number]
        head, base = self.branches[pr["head"]], self.branches[pr["base"]]
        changed = {p for p in set(head) | set(base) if head.get(p) != base.get(p)}
        if any(p.startswith(self.review_required) for p in changed if self.review_required):
            return False, "review required"
        self.branches["main"] = dict(head)
        pr["merged"] = True
        return True, ""

    def approve_and_merge(self, number):  # a human, later
        pr = self.prs[number]
        self.branches["main"] = dict(self.branches[pr["head"]])
        pr["merged"] = True

    def pr_state(self, number):
        return "merged" if self.prs[number]["merged"] else "open"


def _publish(store, slug, category, body, *, author=ALICE, tags=None, kind="md", title=None):
    return pub.publish(
        store,
        PublishRequest(
            title=title or f"Doc {slug}",
            content=body,
            kind=kind,
            category=category,
            author=author,
            slug=slug,
            tags=tags,
        ),
    )


def _repo(store, slug):
    return pub.doc_payload(store, store.get(slug))["repo"]


def test_first_run_writes_new_documents_and_recognizes_repo_ones(store):
    repo_text = "---\ntitle: 数仓指南\n---\n\n# 数仓指南\n\n正文\n"
    importer.import_file(store, "dw/zh/guide.md", repo_text, author=BOB)
    doc, _, _ = _publish(store, "r1", "algorithm/reports", "# Report 1\n\n第一版", tags=["a"])
    gh = FakeGitHub({"dw/zh/guide.md": repo_text})

    summary = repo_sync.run_once(store, gh)
    assert [a.path for a in summary.committed] == ["algorithm/reports/r1.md"]
    assert summary.merged and summary.pr_url.endswith("/pull/1")
    assert gh.commits[0][1] == ALICE and "add Doc r1" in gh.commits[0][2]
    written = gh.branches["main"]["algorithm/reports/r1.md"]
    meta = frontmatter.loads(written)
    assert meta["title"] == "Doc r1" and meta["tags"] == ["a"] and meta["author"] == ALICE
    assert meta.content.strip() == "# Report 1\n\n第一版"
    assert any(c[0] == "delete_branch" for c in gh.calls)  # the sync branch is disposable
    repo = _repo(store, "r1")
    assert repo["state"] == "synced" and repo["path"] == "algorithm/reports/r1.md"
    guide = store.by_source_path("dw/zh/guide.md")
    assert _repo(store, guide.slug)["state"] == "synced"

    # nothing to do now
    assert repo_sync.run_once(store, gh).planned == []

    # a new version -> an update commit; a metadata change -> the frontmatter changes
    _publish(store, "r1", "algorithm/reports", "# Report 1\n\n第二版")
    summary = repo_sync.run_once(store, gh)
    assert "update Doc r1 (v2)" in gh.commits[-1][2]
    assert (
        frontmatter.loads(gh.branches["main"]["algorithm/reports/r1.md"])
        .content.strip()
        .endswith("第二版")
    )
    pub.update_meta(store, "r1", tags=["a", "b"], status="approved")
    summary = repo_sync.run_once(store, gh)
    assert [a.path for a in summary.committed] == ["algorithm/reports/r1.md"]
    assert frontmatter.loads(gh.branches["main"]["algorithm/reports/r1.md"])["status"] == "approved"

    # the file coming back through the repository sync is the same document, unchanged
    back = gh.branches["main"]["algorithm/reports/r1.md"]
    same, version, outcome = importer.import_file(
        store, "algorithm/reports/r1.md", back, author=BOB
    )
    assert same.slug == doc.slug and outcome == "unchanged" and version.version_no == 2


def test_archived_document_is_removed_from_the_repository(store):
    _publish(store, "r2", "algorithm/reports", "# R2\n\n正文")
    gh = FakeGitHub()
    repo_sync.run_once(store, gh)
    assert "algorithm/reports/r2.md" in gh.branches["main"]
    pub.archive(store, "r2")
    summary = repo_sync.run_once(store, gh)
    assert [a.path for a in summary.committed] == ["algorithm/reports/r2.md"]
    assert "archive" in gh.commits[-1][2] and "algorithm/reports/r2.md" not in gh.branches["main"]
    assert _repo(store, "r2")["state"] == "deleted"
    assert repo_sync.run_once(store, gh).planned == []


def test_review_required_leaves_the_pull_request_open_until_a_human_merges(store):
    _publish(store, "inc1", "incidents", "# Incident\n\n正文")
    gh = FakeGitHub(review_required=("incidents/",))
    summary = repo_sync.run_once(store, gh)
    assert summary.merged is False and summary.pr_url.endswith("/pull/1")
    repo = _repo(store, "inc1")
    assert repo["state"] == "pending_review" and "review required" in repo["error"]
    assert repo_sync.run_once(store, gh).planned == []  # waiting, not retried
    gh.approve_and_merge(1)
    repo_sync.run_once(store, gh)
    assert _repo(store, "inc1")["state"] == "synced"


def test_skipped_categories_and_path_conflicts(store, monkeypatch):
    monkeypatch.setattr(get_settings(), "repo_sync_skip_categories", "demo")
    _publish(store, "demo1", "demo", "# Demo\n\n正文")
    importer.import_file(store, "dw/zh/readme.md", "# 指南\n\n正文", author=BOB)
    # a site-published document whose natural path is already someone else's file
    _publish(store, "readme", "dw/zh", "# Another\n\n正文")
    gh = FakeGitHub({"dw/zh/readme.md": "# 指南\n\n正文"})
    summary = repo_sync.run_once(store, gh)
    # the imported one is already in git; only the clashing site document is work
    assert [a.path for a in summary.planned] == ["dw/zh/readme.md"]
    assert summary.committed == [] and summary.skipped and "belongs to" in summary.skipped[0]
    assert _repo(store, "readme")["state"] == "error"


def test_dry_run_plans_without_touching_github(store):
    _publish(store, "r3", "product", "# R3\n\n正文")
    gh = FakeGitHub()
    summary = repo_sync.run_once(store, gh, dry_run=True)
    assert [a.path for a in summary.planned] == ["product/r3.md"] and gh.calls == []
    assert store.repo_binding("r3") is None


def test_export_text_shapes():
    when = dt.datetime(2026, 9, 10, 8, 0)
    doc = Document(
        slug="t",
        title="T",
        category="x",
        kind="md",
        created_by=ALICE,
        created_at=when,
        updated_at=when,
    )
    text = repo_sync.export_text(doc, "# T\n\nbody")
    assert text.startswith("---\n") and "author: " + ALICE in text and text.endswith("body\n")
    assert "created: '2026-09-10'" in text or "created: 2026-09-10" in text
    assert repo_sync.export_text(doc, "---\nx: 1\n---\n# own\n") == "---\nx: 1\n---\n# own\n"
    assert (
        repo_sync.export_text(doc, "# from git\n", from_repo=True) == "# from git\n"
    )  # mirrored verbatim
    html_doc = Document(
        slug="h",
        title="H",
        category="x",
        kind="html",
        created_by=ALICE,
        created_at=when,
        updated_at=when,
    )
    assert repo_sync.export_text(html_doc, "<h1>hi</h1>") == "<h1>hi</h1>\n"


def test_dispatch_mode_only_starts_the_workflow(store, monkeypatch):
    """A credential that may only start workflows: the site plans, the
    repository's own workflow writes."""
    monkeypatch.setattr(get_settings(), "repo_sync_mode", "dispatch")
    _publish(store, "d1", "product", "# D1\n\n正文")
    gh = FakeGitHub()
    summary = repo_sync.run_once(store, gh)
    assert summary.dispatched and [a.path for a in summary.planned] == ["product/d1.md"]
    assert gh.dispatched == [("sync-from-docstate.yml", "main")] and gh.commits == []
    # the path is reserved before anyone writes it, so the file coming back
    # through the publish Action maps to this document and not to a new one
    repo = _repo(store, "d1")
    assert repo["path"] == "product/d1.md" and repo["state"] == "pending"

    payload = repo_sync.pending_payload(store)
    assert payload["base"] == "main" and len(payload["files"]) == 1
    f = payload["files"][0]
    assert f["path"] == "product/d1.md" and f["action"] == "write"
    assert f["message"] == "docs(product): add Doc d1 (v1)" and f["author"]["email"] == ALICE
    assert frontmatter.loads(f["content"])["title"] == "Doc d1"


def test_the_repository_push_back_is_the_acknowledgement(client, store, monkeypatch):
    monkeypatch.setattr(get_settings(), "repo_sync_mode", "dispatch")
    _publish(store, "d2", "product", "# D2\n\n第一版")
    assert _repo(store, "d2") is None
    exported = repo_sync.pending_payload(store)["files"][0]

    # what the workflow committed comes back through the publish Action
    r = client.post(
        "/api/import",
        json={"ref": "abc", "files": [{"path": exported["path"], "content": exported["content"]}]},
    )
    assert r.status_code == 200 and r.json()["counts"] == {"unchanged": 1}
    repo = _repo(store, "d2")
    assert repo["state"] == "synced" and repo["path"] == "product/d2.md"
    assert repo_sync.pending_payload(store)["files"] == []  # nothing left to write

    # a new version makes it pending again
    _publish(store, "d2", "product", "# D2\n\n第二版")
    assert _repo(store, "d2")["state"] == "pending"


def test_pending_endpoint_is_for_trusted_services(client, store, monkeypatch):
    _publish(store, "d3", "product", "# D3\n\n正文")
    assert client.get("/api/repo-sync/pending").status_code == 200  # fake mode = trusted
    monkeypatch.setattr(get_settings(), "api_tokens", "svc:svc")
    assert client.get("/api/repo-sync/pending").status_code == 403
    r = client.get("/api/repo-sync/pending", headers={"X-Docstate-Token": "svc"})
    assert r.status_code == 200 and r.json()["files"][0]["path"] == "product/d3.md"


def test_documents_that_came_from_the_repository_are_not_planned(store):
    """They are already in git; planning them would produce no diff, nothing
    would come back to acknowledge it, and they would fill every run."""
    doc, _, _ = importer.import_file(store, "dw/zh/from-git.md", "# 来自仓库\n\n正文", author=BOB)
    assert repo_sync.plan(store) == []
    assert _repo(store, doc.slug)["state"] == "synced"

    # metadata changes do not rewrite a mirrored file, so they must not replan it
    pub.update_meta(store, doc.slug, tags=["x"], status="approved")
    assert repo_sync.plan(store) == []

    # a version published on the site does have to be written back
    _publish(store, doc.slug, "dw/zh", "# 来自仓库\n\n站上改的", title="来自仓库")
    assert [a.path for a in repo_sync.plan(store)] == ["dw/zh/from-git.md"]


def test_the_limit_counts_only_real_work(store, monkeypatch):
    monkeypatch.setattr(get_settings(), "repo_sync_max_docs", 2)
    for i in range(4):
        importer.import_file(store, f"dw/zh/g{i}.md", f"# G{i}\n\n仓库里的正文", author=BOB)
    for i in range(3):
        _publish(store, f"s{i}", "product", f"# S{i}\n\n站上发布的")
    planned = repo_sync.plan(store)
    assert [a.doc.slug for a in planned] == [
        "s0",
        "s1",
    ]  # the four mirrored ones do not crowd it out
