"""Write-back planning and execution; see the package docstring.

A run:

1. plans — documents whose latest version or metadata is not what was last
   written (no binding yet, a newer version, changed title/tags/status/summary),
   plus archived documents whose file is still in the repository;
2. settles pull requests left open by an earlier run (a merged one marks its
   documents synced; an open one keeps them out of this run);
3. compares each export with the file on the base branch — identical means
   "synced" without a commit — and commits the rest on one branch, one commit
   per document, author = the person who published it;
4. opens one pull request and merges it (rebase, linear history). Where the
   repository's rules want a human review it stays open and the run records
   the URL.

Exported Markdown carries frontmatter (title, tags, status, author, dates)
unless the document already had its own; the site's change detection ignores
frontmatter, so the file coming back through the repository sync is
"unchanged" and creates no version."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from dataclasses import dataclass, field

import frontmatter

from docstate.core.clock import utcnow
from docstate.core.models import Document, RepoBinding
from docstate.core.text import normalize_category
from docstate.settings import get_settings
from docstate.storage.base import DocumentStore

from .client import GitHubClient, GitHubError

log = logging.getLogger("docstate.repo_sync")

FALLBACK_AUTHOR = "docstate@localhost"


@dataclass
class Action:
    doc: Document
    path: str
    text: str | None  # None = delete
    sha: str = ""  # sha256 of text
    meta_sha: str = ""
    reason: str = ""


@dataclass
class Summary:
    dispatched: bool = False
    planned: list[Action] = field(default_factory=list)
    committed: list[Action] = field(default_factory=list)
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pr_url: str | None = None
    merged: bool | None = None

    def as_dict(self) -> dict:
        return {
            "dispatched": self.dispatched,
            "planned": [a.path for a in self.planned],
            "committed": [a.path for a in self.committed],
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "errors": self.errors,
            "pr_url": self.pr_url,
            "merged": self.merged,
        }


# ------------------------------------------------------------------ export
def meta_sha(doc: Document) -> str:
    """Only what the export writes (frontmatter + the path's category), so a
    change the file cannot show never schedules a rewrite."""
    key = json.dumps([doc.title, list(doc.tags), doc.status, doc.category], ensure_ascii=False)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def export_text(
    doc: Document, content: str, *, version_at: dt.datetime | None = None, from_repo: bool = False
) -> str:
    """The file as it should be in the repository. HTML, Markdown that already
    has frontmatter, and a version that itself came from the repository go
    verbatim (so mirroring never rewrites files); Markdown published on the
    site gets its metadata as frontmatter."""
    if from_repo:
        return content  # byte-for-byte what the repository holds
    if doc.kind != "md" or content.lstrip().startswith("---"):
        return content if content.endswith("\n") else content + "\n"
    meta: dict = {"title": doc.title}
    if doc.tags:
        meta["tags"] = list(doc.tags)
    meta["status"] = doc.status
    meta["author"] = doc.created_by
    meta["created"] = doc.created_at.date().isoformat()
    meta["updated"] = (version_at or doc.updated_at).date().isoformat()
    post = frontmatter.Post(content.strip() + "\n", **meta)
    return frontmatter.dumps(post) + "\n"


def repo_path(store: DocumentStore, doc: Document) -> str:
    """Where the document lives in the repository: the path it came from or
    was written to before, else <category>/<slug>.<ext>."""
    row = store.repo_binding(doc.slug)
    if row is not None and row.path:
        return row.path
    for v in store.versions(doc.slug):  # newest first
        if v.source_path:
            return v.source_path
    ext = "md" if doc.kind == "md" else "html"
    category = normalize_category(doc.category)
    return (
        f"{category}/{doc.slug}.{ext}" if category not in ("", "general") else f"{doc.slug}.{ext}"
    )


def _skipped(doc: Document, skip: frozenset[str]) -> bool:
    top = (doc.category or "").split("/", 1)[0].lower()
    return top in skip or doc.category.lower() in skip


def _binding(store: DocumentStore, doc: Document, path: str) -> RepoBinding:
    """The document's binding, created in memory if there is none; the caller saves it."""
    row = store.repo_binding(doc.slug) or RepoBinding(slug=doc.slug, path=path)
    row.path = path
    row.updated_at = utcnow()
    return row


# ------------------------------------------------------------------ plan
def plan(store: DocumentStore, *, limit: int | None = None) -> list[Action]:
    """What still has to reach the repository. A document whose current
    version came from the repository is already there — recorded and skipped,
    not handed out as work: the writer would produce no diff, nothing would
    come back, and it would be planned again forever."""
    skip = get_settings().repo_sync_skip_list
    limit = limit or get_settings().repo_sync_max_docs
    actions: list[Action] = []
    for doc in store.iter_all():
        if _skipped(doc, skip):
            continue
        row = store.repo_binding(doc.slug)
        if doc.archived_at is not None:
            # in the repository (written there, or it came from there) and not yet removed
            in_repo = (
                row is not None
                and row.deleted_at is None
                and (
                    row.synced_version is not None
                    or any(v.source_path for v in store.versions(doc.slug))
                )
            )
            if in_repo:
                actions.append(Action(doc, row.path, None, reason="archived"))
            continue
        if row is not None and row.pr_state == "open":
            continue  # waiting for a human on an earlier pull request
        current_meta = meta_sha(doc)
        if (
            row is not None
            and row.synced_version == doc.latest_version
            and row.meta_sha == current_meta
        ):
            continue
        version = store.get_version(doc.slug, None)
        if version is None:
            continue
        path = repo_path(store, doc)
        if version.source_path == path:
            # this content is in the repository because it came from there
            row = _binding(store, doc, path)
            row.synced_version = doc.latest_version
            row.synced_sha = version.content_sha
            row.meta_sha = current_meta
            row.pr_state = row.pr_state or "merged"
            row.last_error = None
            store.save_repo_binding(row)
            continue
        owner = store.by_source_path(path)
        if owner is not None and owner.slug != doc.slug:
            actions.append(Action(doc, path, None, reason=f"path {path} belongs to {owner.slug}"))
            continue
        text = export_text(
            doc,
            version.content,
            version_at=version.created_at,
            from_repo=version.source_path is not None,
        )
        actions.append(
            Action(
                doc,
                path,
                text,
                sha=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                meta_sha=current_meta,
                reason="new" if row is None else "changed",
            )
        )
        if len(actions) >= limit:
            break
    return actions


# ------------------------------------------------------------------ run
def commit_message(action: Action, *, first_write: bool) -> str:
    doc = action.doc
    if action.text is None:
        return f"docs: archive {doc.title} ({doc.slug})"
    verb = "add" if first_write else "update"
    return f"docs({doc.category}): {verb} {doc.title} (v{doc.latest_version})"


def reserve(store: DocumentStore, actions: list[Action]) -> None:
    """Record where each document is about to be written, before anyone
    writes it. Without this the file coming back through the repository's
    publish Action would not map to the document that produced it, and the
    site would grow a duplicate."""
    for action in actions:
        if action.text is None and not action.reason.startswith("archived"):
            continue
        row = _binding(store, action.doc, action.path)
        row.pending_action = "delete" if action.text is None else "write"
        row.pending_version = action.doc.latest_version
        store.save_repo_binding(row)


def pending_payload(store: DocumentStore) -> dict:
    """What the repository's own workflow should write (dispatch mode): the
    same plan, as data. The result comes back through the repository's publish
    Action, which is what acknowledges the write."""
    actions = plan(store)
    reserve(store, actions)
    files = []
    for action in actions:
        if action.text is None and not action.reason.startswith("archived"):
            continue  # a path conflict is not the workflow's problem
        row = store.repo_binding(action.doc.slug)
        files.append(
            {
                "path": action.path,
                "action": "delete" if action.text is None else "write",
                "content": action.text,
                "message": commit_message(
                    action, first_write=row is None or row.synced_version is None
                ),
                "author": _author(action.doc),
                "slug": action.doc.slug,
                "title": action.doc.title,
            }
        )
    return {"base": get_settings().github_branch, "files": files}


def _author(doc: Document) -> dict:
    email = doc.created_by or FALLBACK_AUTHOR
    return {"name": email.split("@")[0], "email": email}


def settle_open_prs(store: DocumentStore, gh: GitHubClient) -> None:
    """Pull requests an earlier run left for review: merged -> synced."""
    for row in store.repo_bindings(pr_state="open"):
        if not row.pr_number:
            row.pr_state = None
            store.save_repo_binding(row)
            continue
        try:
            state = gh.pr_state(row.pr_number)
        except GitHubError as e:
            row.last_error = str(e)
            store.save_repo_binding(row)
            continue
        if state == "merged":
            row.pr_state = "merged"
            row.last_error = None
            if row.pending_action == "delete":
                row.deleted_at = utcnow()
            elif row.pending_action == "write":
                row.synced_version = row.pending_version
            row.pending_action = row.pending_version = None
        elif state == "closed":
            row.pr_state = None  # declined: try again with a fresh pull request
            row.pending_action = row.pending_version = None
        row.updated_at = utcnow()
        store.save_repo_binding(row)


def run_once(store: DocumentStore, gh: GitHubClient | None, *, dry_run: bool = False) -> Summary:
    s = get_settings()
    summary = Summary()
    dispatch = s.repo_sync_mode == "dispatch"
    if gh is not None and not dry_run and not dispatch:
        settle_open_prs(store, gh)
    summary.planned = plan(store)
    if dry_run or not summary.planned:
        return summary
    assert gh is not None
    if dispatch:
        # this credential may only start workflows; the repository's own
        # workflow fetches /api/repo-sync/pending and does the writing
        reserve(store, summary.planned)
        gh.dispatch_workflow(s.github_dispatch_workflow, s.github_branch)
        summary.dispatched = True
        log.info(
            "dispatched %s for %d document(s)", s.github_dispatch_workflow, len(summary.planned)
        )
        return summary

    base_branch = s.github_branch
    pending: list[tuple[Action, str | None]] = []  # (action, existing file sha)
    for action in summary.planned:
        if action.text is None and not action.reason.startswith("archived"):
            summary.skipped.append(f"{action.path}: {action.reason}")
            row = _binding(store, action.doc, action.path)
            row.last_error = action.reason
            store.save_repo_binding(row)
            continue
        try:
            existing = gh.get_file(action.path, ref=base_branch)
        except GitHubError as e:
            summary.errors.append(f"{action.path}: {e}")
            row = _binding(store, action.doc, action.path)
            row.last_error = str(e)
            store.save_repo_binding(row)
            continue
        row = _binding(store, action.doc, action.path)
        if action.text is None:  # archived: remove the file
            if existing is None:
                row.deleted_at = utcnow()
                row.last_error = None
                summary.unchanged += 1
            else:
                pending.append((action, existing.sha))
        elif existing is not None and existing.text.rstrip("\n") == action.text.rstrip("\n"):
            row.synced_version = action.doc.latest_version
            row.synced_sha = action.sha
            row.meta_sha = action.meta_sha
            row.pr_state = row.pr_state or "merged"
            row.last_error = None
            summary.unchanged += 1
        else:
            pending.append((action, existing.sha if existing else None))
        store.save_repo_binding(row)
    if not pending:
        return summary

    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    branch = f"docstate/sync-{stamp}"
    try:
        gh.create_branch(branch, gh.branch_sha(base_branch))
    except GitHubError as e:
        summary.errors.append(f"branch: {e}")
        return summary
    for action, existing_sha in pending:
        doc = action.doc
        try:
            message = commit_message(action, first_write=not existing_sha)
            if action.text is None:
                gh.delete_file(
                    action.path,
                    sha=existing_sha or "",
                    message=message,
                    branch=branch,
                    author=_author(doc),
                )
            else:
                gh.put_file(
                    action.path,
                    action.text,
                    message=message,
                    branch=branch,
                    sha=existing_sha,
                    author=_author(doc),
                )
            summary.committed.append(action)
        except GitHubError as e:
            summary.errors.append(f"{action.path}: {e}")
            row = _binding(store, doc, action.path)
            row.last_error = str(e)
            store.save_repo_binding(row)
    if not summary.committed:
        gh.delete_branch(branch)
        return summary

    lines = [
        f"- {'archive ' if a.text is None else ''}`{a.path}` — {a.doc.title} ({s.public_base_url}/d/{a.doc.slug})"
        for a in summary.committed
    ]
    n = len(summary.committed)
    try:
        pr = gh.create_pr(
            head=branch,
            base=base_branch,
            title=f"docstate: sync {n} document{'s' if n > 1 else ''}",
            body="Written back by Docstate (repository write-back).\n\n" + "\n".join(lines) + "\n",
        )
        merged, reason = gh.merge_pr(pr.number, method="rebase")
    except GitHubError as e:
        summary.errors.append(f"pull request: {e}")
        for action in summary.committed:
            row = _binding(store, action.doc, action.path)
            row.last_error = str(e)
            store.save_repo_binding(row)
        return summary
    summary.pr_url, summary.merged = pr.url, merged
    for action in summary.committed:
        row = _binding(store, action.doc, action.path)
        row.pr_number, row.pr_url = pr.number, pr.url
        row.pr_state = "merged" if merged else "open"
        row.last_error = None if merged else f"waiting for review: {reason}"
        row.pending_action = None if merged else ("delete" if action.text is None else "write")
        row.pending_version = None if merged else action.doc.latest_version
        if action.text is None:
            if merged:
                row.deleted_at = utcnow()
        else:
            row.synced_sha = action.sha
            row.meta_sha = action.meta_sha
            if merged:
                row.synced_version = action.doc.latest_version
        store.save_repo_binding(row)
    if merged:
        gh.delete_branch(branch)
    return summary


def mark_synced(store: DocumentStore, doc: Document, path: str, content: str) -> None:
    """The repository holds exactly this content for this document — recorded
    when the file arrives through /api/import, which is what closes the loop
    once the workflow's pull request has merged."""
    row = _binding(store, doc, path)
    row.synced_version = doc.latest_version
    row.synced_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    row.meta_sha = meta_sha(doc)
    row.pr_state = "merged"
    row.pending_action = row.pending_version = None
    row.deleted_at = None
    row.last_error = None
    store.save_repo_binding(row)


def mark_deleted(store: DocumentStore, doc: Document, path: str) -> None:
    row = _binding(store, doc, path)
    row.deleted_at = utcnow()
    row.pending_action = row.pending_version = None
    row.last_error = None
    store.save_repo_binding(row)


def build_client() -> GitHubClient | None:
    s = get_settings()
    if not s.repo_sync_enabled:
        return None
    permissions = (
        {"actions": "write"}
        if s.repo_sync_mode == "dispatch"
        else {"contents": "write", "pull_requests": "write"}
    )
    return GitHubClient(
        s.github_repo,
        api_url=s.github_api_url,
        token=s.github_token.get_secret_value(),
        app_id=s.github_app_id,
        app_private_key=s.github_app_private_key.get_secret_value(),
        permissions=permissions,
        timeout=s.repo_sync_timeout_seconds,
    )
