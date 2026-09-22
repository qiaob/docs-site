"""JSON API: document state (used by the shell page on behalf of sandboxed
documents), publish, bulk import, documents, search, health.

The MCP server (`docstate-mcp`), the CLI and a GitHub Action are clients of
this API; nothing else writes."""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections import Counter

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from docstate import auth
from docstate.core import checks, importer
from docstate.core import publish as pub
from docstate.core.models import DocQuery, PublishRequest
from docstate.core.text import normalize_category
from docstate.integrations.github import repo_sync
from docstate.settings import get_settings
from docstate.storage import StorageError

from .deps import get_storage

audit = logging.getLogger("docstate.audit")

_KEY_RE = re.compile(r"^[\w.\-:]{1,200}$")
CSRF_HEADER_VALUE = "docstate"
MAX_IMPORT_BYTES = 50 * 1024 * 1024


# ------------------------------------------------------------------ state
def _state_response(entry, key: str, scope: str) -> JSONResponse:
    return JSONResponse(
        {
            "key": key,
            "scope": scope,
            "value": entry.value if entry else None,
            "updated_by": entry.updated_by if entry else None,
            "updated_at": (entry.updated_at.isoformat() + "Z") if entry else None,
        }
    )


def _scope_owner(request: Request, viewer: str) -> tuple[str, str]:
    scope = request.query_params.get("scope", "me")
    if scope not in ("me", "shared"):
        scope = "me"
    return scope, (viewer if scope == "me" else "")


async def state_get(request: Request):
    viewer = auth.require_viewer(request)
    auth.require(viewer, auth.READ)
    slug, key = request.path_params["slug"], request.path_params["key"]
    if not _KEY_RE.match(key):
        return JSONResponse({"error": "bad key"}, status_code=400)
    scope, owner = _scope_owner(request, viewer)
    storage = get_storage()
    if storage.docs.get(slug) is None:
        return PlainTextResponse("not found", status_code=404)
    return _state_response(storage.state.get(slug, key, owner), key, scope)


async def state_put(request: Request):
    # A custom header cannot be sent by a cross-site form, which is all the
    # CSRF protection this cookie-authenticated write needs.
    if request.headers.get("x-requested-with") != CSRF_HEADER_VALUE:
        return JSONResponse({"error": "missing X-Requested-With"}, status_code=403)
    viewer = auth.require_viewer(request)
    auth.require(viewer, auth.READ)
    slug, key = request.path_params["slug"], request.path_params["key"]
    if not _KEY_RE.match(key):
        return JSONResponse({"error": "bad key"}, status_code=400)
    scope, owner = _scope_owner(request, viewer)
    body = await request.body()
    if len(body) > get_settings().max_state_bytes:
        return JSONResponse({"error": "state too large"}, status_code=413)
    try:
        value = json.loads(body or b"{}").get("value")
    except (ValueError, AttributeError):
        return JSONResponse({"error": "body must be JSON {value: ...}"}, status_code=400)
    storage = get_storage()
    if storage.docs.get(slug) is None:
        return PlainTextResponse("not found", status_code=404)
    entry = storage.state.set(slug, key, owner, value, viewer)
    audit.info("state.set slug=%s key=%s scope=%s by=%s", slug, key, scope, viewer)
    return _state_response(entry, key, scope)


# ------------------------------------------------------------------ publish
async def publish(request: Request):
    s_ = get_settings()
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    content = payload.get("content") or ""
    if len(content.encode("utf-8")) > s_.max_doc_bytes:
        return JSONResponse({"error": "content exceeds size limit"}, status_code=413)
    kind = (payload.get("kind") or "md").lower()
    if kind not in ("md", "html"):
        return JSONResponse({"error": "kind must be one of ('md', 'html')"}, status_code=400)
    author, trusted = auth.api_caller(request, fallback=payload.get("author"))
    if not trusted:
        auth.require(author, auth.PUBLISH)
    store = get_storage().docs
    try:
        warnings = checks.warnings_for(
            store,
            content,
            kind,
            source_path=payload.get("source_path"),
            repo_url=s_.source_repo_url,
        )
        if payload.get("dry_run"):
            # everything but the write: the caller sees what the site would flag
            return JSONResponse(
                {
                    "outcome": "dry_run",
                    "slug": payload.get("slug"),
                    "category": normalize_category(payload.get("category")),
                    "warnings": warnings,
                }
            )
        doc, version, outcome = pub.publish(
            store,
            PublishRequest(
                title=payload.get("title") or "",
                content=content,
                kind=kind,
                category=payload.get("category") or "misc",
                author=author,
                slug=payload.get("slug"),
                tags=payload.get("tags"),
                summary=payload.get("summary"),
                label=payload.get("label"),
                source_path=payload.get("source_path"),
                status=payload.get("status"),
            ),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    audit.info(
        "publish slug=%s version=%s outcome=%s by=%s", doc.slug, version.version_no, outcome, author
    )
    return JSONResponse(
        {
            "outcome": outcome,
            "url": f"{s_.public_base_url}/d/{doc.slug}",
            "slug": doc.slug,
            "version": version.version_no,
            "title": doc.title,
            "category": doc.category,
            "warnings": warnings,
        }
    )


def _parse_iso_utc(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.UTC).replace(tzinfo=None)
    return parsed


async def import_files(request: Request):
    """Bulk import from a repository checkout — what a GitHub Action posts
    after a merge. Trusted services only.

    Body: {"ref": "<commit>", "label": "<commit subject>",
           "files": [{"path": "guides/x.md", "content": "...", "author": "a@b",
                      "committed_at": "2026-09-10T02:00:00Z", "deleted": false}]}
    Same path -> same document; unchanged content -> "unchanged"; a deleted
    file archives its document. Files outside the publishable set are skipped."""
    fallback, trusted = auth.api_caller(request, fallback="repo")
    if not trusted:
        return JSONResponse({"error": "import is for trusted services only"}, status_code=403)
    body = await request.body()
    if len(body) > MAX_IMPORT_BYTES:
        return JSONResponse({"error": "import exceeds size limit"}, status_code=413)
    try:
        payload = json.loads(body)
        files = payload.get("files") or []
        assert isinstance(files, list)
    except (ValueError, AssertionError, AttributeError):
        return JSONResponse({"error": "body must be JSON {files: [...]}"}, status_code=400)
    s_ = get_settings()
    store = get_storage().docs
    results: list[dict] = []
    counts: Counter = Counter()
    for f in files:
        path = str(f.get("path") or "").strip().lstrip("/")
        if not path or not importer.wanted(path):
            # outside the publishable set; if an earlier rule set let it in,
            # a full sync after the rule change retires it here
            doc = importer.find_by_source(store, path) if path else None
            if doc is not None and not doc.is_archived:
                pub.archive(store, doc.slug)
                results.append({"path": path, "outcome": "archived", "slug": doc.slug})
                counts["archived"] += 1
            else:
                results.append({"path": path, "outcome": "skipped"})
                counts["skipped"] += 1
            continue
        try:
            if f.get("deleted"):
                doc = importer.archive_path(store, path)
                outcome = "archived" if doc else "missing"
                if doc is not None:
                    repo_sync.mark_deleted(store, doc, path)
                results.append(
                    {"path": path, "outcome": outcome, "slug": doc.slug if doc else None}
                )
                counts[outcome] += 1
                continue
            content = f.get("content")
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            if len(content.encode("utf-8")) > s_.max_doc_bytes:
                raise ValueError("content exceeds size limit")
            if len(content.encode("utf-8")) < importer.MIN_BYTES:
                results.append({"path": path, "outcome": "skipped"})
                counts["skipped"] += 1
                continue
            author = f.get("author") if auth.valid_email(f.get("author")) else fallback
            doc, version, outcome = importer.import_file(
                store,
                path,
                content,
                author=author,
                committed_at=_parse_iso_utc(f.get("committed_at")),
                label=f.get("label") or payload.get("label"),
                tz=s_.zone,
            )
            # the repository now holds this content for this document
            repo_sync.mark_synced(store, doc, path, content)
            results.append(
                {
                    "path": path,
                    "outcome": outcome,
                    "slug": doc.slug,
                    "version": version.version_no,
                    "url": f"{s_.public_base_url}/d/{doc.slug}",
                }
            )
            counts[outcome] += 1
        except ValueError as exc:
            results.append({"path": path, "outcome": "error", "error": str(exc)})
            counts["error"] += 1
    audit.info("import ref=%s files=%d counts=%s", payload.get("ref"), len(files), dict(counts))
    return JSONResponse({"ref": payload.get("ref"), "counts": dict(counts), "results": results})


# ------------------------------------------------------------------ documents
def _reader(request: Request) -> str:
    """Read APIs serve the signed-in reader or the trusted service (which has
    already authorized the person it acts for)."""
    email, trusted = auth.caller(request)
    if not trusted:
        auth.require(email, auth.READ)
    return email


def _int_param(request: Request, name: str, default: int, cap: int) -> int:
    try:
        return min(int(request.query_params.get(name) or default), cap)
    except ValueError:
        return default


async def list_docs(request: Request):
    _reader(request)
    s_ = get_settings()
    store = get_storage().docs
    docs = store.list(
        DocQuery(
            category=request.query_params.get("category"),
            tag=request.query_params.get("tag"),
            q=request.query_params.get("q"),
            status=request.query_params.get("status"),
            limit=_int_param(request, "limit", 100, 1000),
        )
    )
    return JSONResponse([pub.doc_payload(store, d, base_url=s_.public_base_url) for d in docs])


async def search_docs(request: Request):
    _reader(request)
    s_ = get_settings()
    store = get_storage().docs
    q = (request.query_params.get("q") or "").strip()
    if not q:
        return JSONResponse({"error": "q is required"}, status_code=400)
    hits = pub.search(store, q, limit=_int_param(request, "limit", 50, 200))
    return JSONResponse(
        [
            {**pub.doc_payload(store, h.doc, base_url=s_.public_base_url), "snippet": h.snippet}
            for h in hits
        ]
    )


async def categories(request: Request):
    """The category tree with document counts — the shape of the site, without
    the documents themselves (that is /api/docs)."""
    _reader(request)
    tree = pub.category_tree(get_storage().docs)

    def strip(nodes: list[dict]) -> list[dict]:
        return [
            {
                "path": n["path"],
                "name": n["name"],
                "count": n["count"],
                "children": strip(n["children"]),
            }
            for n in nodes
        ]

    return JSONResponse(strip(tree))


def _load(store, request: Request):
    doc = store.get(request.path_params["slug"])
    if doc is None:
        raise HTTPException(404, "no such document")
    return doc


async def repo_sync_pending(request: Request):
    """What the documentation repository's own workflow should write. Trusted
    services only: it is the write-back plan, not reader-facing."""
    _, trusted = auth.api_caller(request, fallback="repo-sync")
    if not trusted:
        return JSONResponse({"error": "repo sync is for trusted services only"}, status_code=403)
    return JSONResponse(repo_sync.pending_payload(get_storage().docs))


async def get_doc(request: Request):
    """One document's metadata, optionally with the content of one version."""
    _reader(request)
    s_ = get_settings()
    store = get_storage().docs
    doc = _load(store, request)
    raw = request.query_params.get("version")
    try:
        wanted = int(raw) if raw else None
    except ValueError:
        return JSONResponse({"error": "version must be an integer"}, status_code=400)
    version = store.get_version(doc.slug, wanted)
    if version is None:
        return JSONResponse({"error": f"{doc.slug} has no version {wanted}"}, status_code=404)
    include = request.query_params.get("content") in ("1", "true")
    return JSONResponse(
        pub.doc_payload(store, doc, version, include_content=include, base_url=s_.public_base_url)
    )


async def list_versions(request: Request):
    _reader(request)
    s_ = get_settings()
    store = get_storage().docs
    doc = _load(store, request)
    return JSONResponse(
        [pub.version_payload(doc, v, base_url=s_.public_base_url) for v in store.versions(doc.slug)]
    )


async def update_meta(request: Request):
    """Change title / category / tags / summary / status; no new version."""
    author, trusted = auth.api_caller(request)
    if not trusted:
        auth.require(author, auth.PUBLISH)
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    fields = {k: payload.get(k) for k in ("title", "category", "tags", "summary", "status")}
    store = get_storage().docs
    doc = _load(store, request)
    try:
        doc = pub.update_meta(store, doc.slug, **fields)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    audit.info("update_meta slug=%s by=%s fields=%s", doc.slug, author, sorted(fields))
    return JSONResponse(pub.doc_payload(store, doc, base_url=get_settings().public_base_url))


async def archive_doc(request: Request):
    """Soft-delete: the document leaves lists and search, its URL keeps answering."""
    author, trusted = auth.api_caller(request)
    if not trusted:
        auth.require(author, auth.ADMIN)
    store = get_storage().docs
    doc = _load(store, request)
    outcome = "already_archived" if doc.is_archived else "archived"
    if not doc.is_archived:
        doc = pub.archive(store, doc.slug)
    audit.info("archive slug=%s by=%s outcome=%s", doc.slug, author, outcome)
    payload = pub.doc_payload(store, doc, base_url=get_settings().public_base_url)
    payload["outcome"] = outcome
    return JSONResponse(payload)


async def healthz(_request: Request):
    try:
        get_storage().ping()
    except StorageError as exc:  # pragma: no cover - only on a broken database
        return PlainTextResponse(f"storage error: {exc}", status_code=503)
    return PlainTextResponse("ok")


api_routes = [
    Route("/api/state/{slug}/{key}", state_get, methods=["GET"]),
    Route("/api/state/{slug}/{key}", state_put, methods=["PUT"]),
    Route("/api/publish", publish, methods=["POST"]),
    Route("/api/import", import_files, methods=["POST"]),
    Route("/api/docs", list_docs),
    Route("/api/search", search_docs),
    Route("/api/categories", categories),
    Route("/api/repo-sync/pending", repo_sync_pending),
    Route("/api/docs/{slug}/versions", list_versions),
    Route("/api/docs/{slug}/archive", archive_doc, methods=["POST"]),
    Route("/api/docs/{slug}", get_doc),
    Route("/api/docs/{slug}", update_meta, methods=["PATCH"]),
    Route("/healthz", healthz),
]
