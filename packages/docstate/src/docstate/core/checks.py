"""Pre-publish checks: what will look broken once this document renders on
the site. Warnings, never errors — the author decides what to do with them.
Used by /api/publish (returned with the result, or alone for a dry run) and
by the MCP `docs_check` tool."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from docstate.core import publish as pub
from docstate.core import render
from docstate.storage.base import DocumentStore

# Hosts a sandboxed document may load code and styles from (see render.CSP).
ALLOWED_SCRIPT_HOSTS = ("cdnjs.cloudflare.com", "cdn.jsdelivr.net")
ALLOWED_STYLE_HOSTS = ALLOWED_SCRIPT_HOSTS + ("fonts.googleapis.com",)
MAX_WARNINGS = 20

_HREF = re.compile(r'<a\b[^>]*\bhref="([^"]*)"', re.I)
_IMG = re.compile(r'<img\b[^>]*\bsrc="([^"]*)"', re.I)
_SCRIPT = re.compile(r'<script\b[^>]*\bsrc="([^"]*)"', re.I)
_STYLESHEET = re.compile(r'<link\b[^>]*\bhref="([^"]*)"', re.I)
_MISSING_WIKI = re.compile(r'class="wikilink missing" title="\[\[([^"\]]*)\]\]"')


def warnings_for(
    store: DocumentStore,
    content: str,
    kind: str,
    *,
    source_path: str | None = None,
    repo_url: str = "",
) -> list[str]:
    out: list[str] = []
    if kind == "md":
        _check_markdown(store, content, source_path, repo_url, out)
    else:
        _check_html(content, out)
    return out[:MAX_WARNINGS]


def _check_markdown(store, content, source_path, repo_url, out: list[str]) -> None:
    def by_path(rel_path: str) -> str | None:
        target = store.by_source_path(rel_path)
        return target.slug if target is not None and not target.is_archived else None

    html = render.render_markdown_body(
        content,
        resolve=lambda name: pub.resolve_wikilink(store, name),
        source_path=source_path,
        resolve_path=by_path,
        repo_url=repo_url,
    )
    for name in _MISSING_WIKI.findall(html):
        out.append(f"[[{name}]] does not match any published document")
    for href in _HREF.findall(html):
        if href.startswith("/d/"):
            slug = href[3:].split("#", 1)[0].split("?", 1)[0]
            if not slug or store.get(slug) is None:
                out.append(f"internal link points to a document that does not exist: {href}")
        elif render.is_relative_url(href):
            out.append(f"relative link cannot be resolved and will 404 for readers: {href}")
    for src in _IMG.findall(html):
        if render.is_relative_url(src):
            out.append(
                f"relative image will not display (the site does not serve repository assets yet): {src}"
            )


def _check_html(content: str, out: list[str]) -> None:
    if not re.search(r"<body\b", content, re.I):
        out.append("HTML has no <body>; this may not be a complete page")
    for src in _SCRIPT.findall(content):
        if render.is_relative_url(src):
            out.append(f"relative script will not load: {src}")
        elif (host := urlsplit(src).hostname) and host not in ALLOWED_SCRIPT_HOSTS:
            out.append(
                f"external script is blocked by the CSP (only cdnjs / jsdelivr are allowed): {src}"
            )
    for href in _STYLESHEET.findall(content):
        if render.is_relative_url(href):
            out.append(f"relative stylesheet will not load: {href}")
        elif (host := urlsplit(href).hostname) and host not in ALLOWED_STYLE_HOSTS:
            out.append(
                f"external stylesheet is blocked by the CSP (only cdnjs / jsdelivr / Google Fonts are allowed): {href}"
            )
    for src in _IMG.findall(content):
        if render.is_relative_url(src):
            out.append(f"relative image will not display: {src}")
