"""Single ASGI entry point: the reader site, the JSON API, static files and
(when DOCSTATE_MCP is on) the MCP endpoint at /mcp.

The MCP endpoint is the same server the standalone `docstate-mcp` package
runs, mounted in-process: its tools call this application's own HTTP API
through an in-memory ASGI transport, so there is exactly one code path for
publishing whether the request comes from a browser, curl or an agent."""

from __future__ import annotations

import logging
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from docstate import auth
from docstate.core import render
from docstate.settings import Settings, get_settings

from .api import api_routes
from .deps import get_storage
from .i18n import translator
from .web import page_routes, templates

log = logging.getLogger("docstate")


async def _denied(request: Request, exc: HTTPException):
    """401/403 as JSON for API callers, as a page with the way forward for people."""
    s = get_settings()
    if request.url.path.startswith("/api/") or "text/html" not in request.headers.get("accept", ""):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    t = translator(s.lang)
    ctx = {
        "site_title": s.site_title,
        "lang": s.lang,
        "t": t,
        "title": t("sign_in_required") if exc.status_code == 401 else t("forbidden"),
        "message": exc.detail,
        "login_url": s.login_url if exc.status_code == 401 else "",
    }
    return templates.TemplateResponse(request, "denied.html", ctx, status_code=exc.status_code)


def _routes() -> list:
    return [
        *page_routes,
        *api_routes,
        Mount("/static", app=StaticFiles(directory=str(render.STATIC_DIR)), name="static"),
    ]


def _with_mcp(settings: Settings, routes: list) -> Starlette:
    """The MCP server as the root application, the site's routes appended."""
    try:
        import httpx

        from docstate_mcp.client import DocstateClient
        from docstate_mcp.server import build_server
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RuntimeError("DOCSTATE_MCP=true needs the docstate-mcp package installed") from exc

    site = Starlette(routes=routes)
    site.add_exception_handler(401, _denied)
    site.add_exception_handler(403, _denied)
    tokens = settings.api_token_map
    token = next(iter(tokens), None)
    client = DocstateClient(
        settings.public_base_url,
        token=token,
        author=None if token else settings.mcp_author,
        transport=httpx.ASGITransport(app=site),
        token_header=settings.api_token_header,
        author_header=settings.author_header,
    )
    root = Path(settings.mcp_source_root) if settings.mcp_source_root else None
    mcp = build_server(client, source_root=root)
    app = mcp.http_app(path="/mcp")
    app.router.routes.extend(routes)
    return app


def create_app(settings: Settings | None = None) -> Starlette:
    s = settings or get_settings()
    logging.basicConfig(
        level=s.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    auth.check_startup(s)
    storage = get_storage()
    if s.auto_migrate:
        storage.init()
    log.info("storage: %s", storage.describe())
    routes = _routes()
    app = _with_mcp(s, routes) if s.mcp else Starlette(routes=routes)
    app.add_middleware(auth.AnonymousIdMiddleware)
    app.add_exception_handler(401, _denied)
    app.add_exception_handler(403, _denied)
    return app


app = create_app()
