"""Reader-facing pages (server-rendered Jinja2)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from docstate import auth
from docstate.core import publish as pub
from docstate.core import render
from docstate.core.clock import to_local
from docstate.core.models import DocQuery
from docstate.core.text import normalize_category
from docstate.settings import get_settings

from .deps import get_storage
from .i18n import translator, ui_strings

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))


def fmt_local(value: dt.datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    local = to_local(value, get_settings().zone)
    return local.strftime(fmt) if local else ""


templates.env.filters["local"] = fmt_local


def _ctx(request: Request, **extra) -> dict:
    """Common template context: viewer, strings, category tree (every page has the sidebar)."""
    s = get_settings()
    store = get_storage().docs
    viewer = auth.require_viewer(request)
    auth.require(viewer, auth.READ)
    t = translator(s.lang)
    tree = pub.category_tree(store)
    return {
        "request": request,
        "viewer": viewer,
        "viewer_label": auth.viewer_label(viewer, t("guest")),
        "viewers": s.demo_viewer_list,
        "auth_mode": s.auth_mode,
        "base_url": s.public_base_url,
        "site_title": s.site_title,
        "lang": s.lang,
        "t": t,
        "logout_url": s.logout_url,
        "tree_nodes": tree,
        "total": sum(n["count"] for n in tree),
        "current": "",
        "current_slug": "",
        **extra,
    }


def _crumbs(category: str) -> list[tuple[str, str]]:
    parts = category.split("/")
    return [("/".join(parts[: i + 1]), part) for i, part in enumerate(parts)]


def _not_found(key: str = "doc_not_found") -> Response:
    return PlainTextResponse(translator(get_settings().lang)(key), status_code=404)


def _eyebrow(doc, version) -> str:
    parts = [p.upper() for p in doc.category.split("/")]
    parts.append(fmt_local(version.created_at, "%Y-%m-%d"))
    parts.append(auth.viewer_label(doc.created_by))
    if version.label:
        parts.append(version.label)
    return " · ".join(parts)


async def home(request: Request):
    store = get_storage().docs
    ctx = _ctx(request, docs=store.list(DocQuery(limit=40)), readme=pub.readme_for(store, ""))
    return templates.TemplateResponse(request, "home.html", ctx)


async def category(request: Request):
    store = get_storage().docs
    cat = normalize_category(request.path_params["category"])
    ctx = _ctx(
        request,
        docs=store.list(DocQuery(category=cat)),
        current=cat,
        crumbs=_crumbs(cat),
        readme=pub.readme_for(store, cat),
    )
    return templates.TemplateResponse(request, "category.html", ctx)


async def timeline(request: Request):
    store = get_storage().docs
    cat = request.query_params.get("category") or ""
    ctx = _ctx(
        request,
        groups=pub.timeline(store, category=cat or None, tz=get_settings().zone),
        current=cat,
        tree_mode="t",
    )
    return templates.TemplateResponse(request, "timeline.html", ctx)


async def search(request: Request):
    store = get_storage().docs
    q = (request.query_params.get("q") or "").strip()
    ctx = _ctx(request, q=q, results=pub.search(store, q) if q else [])
    return templates.TemplateResponse(request, "search.html", ctx)


async def doc_page(request: Request):
    store = get_storage().docs
    slug = request.path_params["slug"]
    v_param = request.query_params.get("v")
    doc = store.get(slug)
    if doc is None:
        return _not_found()
    try:
        wanted = int(v_param) if v_param else None
    except ValueError:
        wanted = None
    version = store.get_version(slug, wanted)
    if version is None:
        return _not_found("version_not_found")
    ctx = _ctx(
        request,
        doc=doc,
        version=version,
        versions=store.versions(slug),
        crumbs=_crumbs(doc.category),
        current=doc.category,
        current_slug=doc.slug,
        is_latest=version.version_no == doc.latest_version,
        raw_url=f"/raw/{doc.slug}/{version.version_no}",
        # the sidebar is a file tree: shown on document pages like everywhere
        # else, one remembered toggle for the whole site
        side_default="1",
    )
    return templates.TemplateResponse(request, "doc.html", ctx)


async def versions_page(request: Request):
    store = get_storage().docs
    slug = request.path_params["slug"]
    doc = store.get(slug)
    if doc is None:
        return _not_found()
    ctx = _ctx(request, doc=doc, versions=store.versions(slug), current=doc.category)
    return templates.TemplateResponse(request, "versions.html", ctx)


async def raw(request: Request):
    """The document itself, served for the sandboxed iframe (see render.CSP)."""
    auth.require(auth.require_viewer(request), auth.READ)
    s = get_settings()
    store = get_storage().docs
    slug = request.path_params["slug"]
    n = request.path_params["version"]
    doc = store.get(slug)
    if doc is None:
        return _not_found()
    version = store.get_version(slug, n)
    if version is None:
        return _not_found("version_not_found")
    if doc.kind == "md":

        def by_path(rel_path: str) -> str | None:
            target = store.by_source_path(rel_path)
            return target.slug if target is not None and not target.is_archived else None

        html = render.render_markdown_page(
            version.content,
            doc.title,
            resolve=lambda name: pub.resolve_wikilink(store, name),
            eyebrow=_eyebrow(doc, version),
            source_path=version.source_path,
            resolve_path=by_path,
            repo_url=s.source_repo_url,
            embed=request.query_params.get("embed") == "1",
            lang=s.lang,
            ui=ui_strings(s.lang),
        )
    else:
        html = render.prepare_html(version.content)
    return HTMLResponse(html, headers=render.RAW_HEADERS)


async def src(request: Request):
    """The stored source, unchanged (Markdown text or the original HTML), as a download."""
    auth.require(auth.require_viewer(request), auth.READ)
    store = get_storage().docs
    slug = request.path_params["slug"]
    n = request.path_params["version"]
    doc = store.get(slug)
    if doc is None:
        return _not_found()
    version = store.get_version(slug, n)
    if version is None:
        return _not_found("version_not_found")
    ext = "md" if doc.kind == "md" else "html"
    media = "text/markdown" if doc.kind == "md" else "text/html"
    return Response(
        version.content,
        media_type=f"{media}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{doc.slug}-v{version.version_no}.{ext}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


async def switch_viewer(request: Request):
    """Demo-only identity switch (fake auth mode)."""
    if get_settings().auth_mode != "fake":
        return PlainTextResponse("not found", status_code=404)
    email = request.query_params.get("as", "")
    nxt = request.query_params.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"
    resp = RedirectResponse(nxt, status_code=303)
    if auth.valid_email(email):
        resp.set_cookie(auth.COOKIE, email, httponly=True, samesite="lax", max_age=30 * 86400)
    return resp


page_routes = [
    Route("/", home),
    Route("/c/{category:path}", category),
    Route("/t", timeline),
    Route("/search", search),
    Route("/d/{slug}/versions", versions_page),
    Route("/d/{slug}", doc_page),
    Route("/raw/{slug}/{version:int}", raw),
    Route("/src/{slug}/{version:int}", src),
    Route("/switch", switch_viewer),
]
