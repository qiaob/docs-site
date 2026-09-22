"""Rendering: Markdown -> HTML page, raw HTML pass-through with the bridge
injected, the CSP that sandboxes documents, and plain-text extraction for search."""

from __future__ import annotations

import html as htmllib
import posixpath
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote, unquote

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

_HERE = Path(__file__).parent
STATIC_DIR = _HERE / "static"

# The bridge is inlined, never referenced by URL. A sandboxed document has an
# opaque origin, so the browser treats its subresource requests as cross-site
# and does not attach a login proxy's SameSite=Lax session cookie: a
# <script src="/static/docbridge.js"> would be answered with 401 behind such a
# proxy and the document would lose height reporting, the outline and DocState.
# Inline, there is nothing to request.
_BRIDGE_JS = (STATIC_DIR / "docbridge.js").read_text(encoding="utf-8")
assert "</script" not in _BRIDGE_JS.lower()
BRIDGE_MARK = '<script data-docbridge="1">'
BRIDGE_TAG = f"{BRIDGE_MARK}\n{_BRIDGE_JS}\n</script>"

# `sandbox` without allow-same-origin makes the document an opaque origin: it
# cannot read the reader's cookies nor call the shell's API directly. Only the
# shell page may embed it (frame-ancestors). Inline scripts/styles are what
# AI-generated documents use, so they stay allowed; external code only from the
# two CDNs the documents are told to use.
CSP = (
    "sandbox allow-scripts allow-forms allow-popups allow-modals; "
    "default-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net data: blob:; "
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net "
    "https://fonts.googleapis.com; "
    "font-src * data:; img-src * data: blob:; connect-src 'none'; frame-ancestors 'self'"
)

RAW_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

# What the md wrapper says next to a task-list checkbox; the server passes the
# reader's language, these are the defaults.
DEFAULT_UI = {
    "saved_shared": "Saved · shared with everyone",
    "saved_me": "Saved · only you see this",
    "saved_memory": "This page only",
    "save_failed": "Could not save",
}

_FORMATTER = HtmlFormatter(nowrap=True)
PYGMENTS_CSS = HtmlFormatter(style="friendly").get_style_defs("pre")

_env = Environment(
    loader=FileSystemLoader(str(_HERE / "templates")),
    autoescape=select_autoescape(["html"]),
)
# `tojson` still escapes <, >, & and ' (safe inside <script>); non-ASCII stays readable
_env.policies["json.dumps_kwargs"] = {"sort_keys": True, "ensure_ascii": False}


def _highlight(code: str, lang: str, _attrs: str) -> str:
    if lang == "mermaid":
        return f'<pre class="mermaid">{htmllib.escape(code)}</pre>\n'
    try:
        lexer = get_lexer_by_name(lang or "text")
    except ClassNotFound:
        lexer = get_lexer_by_name("text")
    return highlight(code, lexer, _FORMATTER)


_md = (
    MarkdownIt(
        "commonmark",
        {"html": True, "linkify": True, "typographer": False, "highlight": _highlight},
    )
    .enable(["table", "strikethrough"])
    .use(front_matter_plugin)
    .use(footnote_plugin)
    .use(tasklists_plugin, enabled=True)
    .use(anchors_plugin, max_level=3, permalink=False)
)

_WIKI = re.compile(r"\[\[([^\]\|#]+)(#[^\]\|]*)?(?:\|([^\]]+))?\]\]")
# fenced blocks and inline code spans are left untouched by the wikilink rewrite
_FENCE_SPLIT = re.compile(r"(```.*?```|~~~.*?~~~|`[^`\n]*`)", re.S)


def _wikilinks(text: str, resolve: Callable[[str], str | None]) -> str:
    """Rewrite [[name]] / [[name|label]] outside fenced code. A resolvable name
    becomes a link to /d/<slug> (the bridge routes it to the shell); an unknown
    one stays as marked text whose title names the missing target."""

    def rep(m: re.Match) -> str:
        target = m.group(1).strip()
        anchor = m.group(2) or ""
        label = (m.group(3) or target).strip()
        slug = resolve(target)
        if slug:
            return f'<a class="wikilink" href="/d/{slug}{anchor}">{htmllib.escape(label)}</a>'
        return f'<span class="wikilink missing" title="[[{htmllib.escape(target)}]]">{htmllib.escape(label)}</span>'

    parts = _FENCE_SPLIT.split(text)
    return "".join(p if i % 2 else _WIKI.sub(rep, p) for i, p in enumerate(parts))


# --- repository-relative links ---
# A document imported from a repository links to its neighbours the way the
# repository does: `zh/01-quickstart.md`, `../decisions/004.md`, `sop/`.
# Inside the sandboxed frame those would resolve against /raw/<slug>/... and
# 404, so link_open rewrites them: a published document -> /d/<slug>, a
# directory -> /c/<category>, any other repository file -> the source
# repository (when DOCSTATE_SOURCE_REPO_URL is set). Images stay as written until
# the site serves repository assets.
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
DOC_EXTENSIONS = (".md", ".html", ".htm")


def is_relative_url(url: str) -> bool:
    """A repository-relative reference (not absolute, not a fragment, not a scheme)."""
    return bool(url) and not url.startswith(("#", "/", "data:", "blob:")) and not _SCHEME.match(url)


def resolve_relative(href: str, env: dict) -> str | None:
    """The site URL for a repository-relative href, or None to leave it alone."""
    base_dir = env.get("base_dir")
    if base_dir is None or not href or href.startswith(("#", "/")) or _SCHEME.match(href):
        return None
    path, _, frag = href.partition("#")
    path = unquote(path.split("?", 1)[0])
    if not path:
        return None
    is_dir = path.endswith("/")
    joined = posixpath.normpath(posixpath.join(base_dir, path))
    if joined.startswith(".."):
        return None
    frag = f"#{frag}" if frag else ""
    ext = posixpath.splitext(joined)[1].lower()
    repo_url = (env.get("repo_url") or "").rstrip("/")
    if not is_dir and ext in DOC_EXTENSIONS:
        resolve_path = env.get("resolve_path")
        slug = resolve_path(joined) if resolve_path else None
        if slug:
            return f"/d/{slug}{frag}"
        return f"{repo_url}/{quote(joined)}" if repo_url else None
    if is_dir or not ext:
        return "/" if joined in (".", "") else f"/c/{quote(joined)}"
    return f"{repo_url}/{quote(joined)}" if repo_url else None


def _link_open(self, tokens, idx, options, env):
    tok = tokens[idx]
    href = tok.attrGet("href")
    if href and env:
        new = resolve_relative(str(href), env)
        if new:
            tok.attrSet("href", new)
    return self.renderToken(tokens, idx, options, env)


_md.add_render_rule("link_open", _link_open)


def render_markdown_body(
    source: str,
    resolve: Callable[[str], str | None],
    *,
    source_path: str | None = None,
    resolve_path: Callable[[str], str | None] | None = None,
    repo_url: str = "",
) -> str:
    """`resolve` answers [[wikilinks]]; `source_path` (the repository path this
    text came from) turns on relative-link rewriting, `resolve_path` maps a
    repository path to a published slug."""
    env: dict = {}
    if source_path:
        env = {
            "base_dir": posixpath.dirname(source_path),
            "resolve_path": resolve_path,
            "repo_url": repo_url,
        }
    html = _md.render(_wikilinks(source, resolve), env)
    return _rewrite_raw_html_links(html, env) if env else html


_RAW_HREF = re.compile(r'(<a\b[^>]*\shref=")([^"]+)(")', re.I)


def _rewrite_raw_html_links(html: str, env: dict) -> str:
    """Links written as raw HTML inside Markdown (a styled call-to-action, a
    card) never reach link_open, so they keep the repository-relative href the
    author wrote and 404 inside the sandboxed frame. Rewrite them the same way
    afterwards; markdown links are already absolute by now, so nothing is
    touched twice."""

    def rep(m: re.Match) -> str:
        target = resolve_relative(m.group(2), env)
        return f"{m.group(1)}{target}{m.group(3)}" if target else m.group(0)

    return _RAW_HREF.sub(rep, html)


def _frontmatter(source: str) -> dict:
    try:
        import frontmatter

        return dict(frontmatter.loads(source).metadata)
    except Exception:
        return {}


_LEADING_H1 = re.compile(r"^\s*(<[^>]+>\s*)*<h1\b", re.I)


def render_markdown_page(
    source: str,
    title: str,
    resolve: Callable[[str], str | None],
    eyebrow: str = "",
    *,
    source_path: str | None = None,
    resolve_path: Callable[[str], str | None] | None = None,
    repo_url: str = "",
    embed: bool = False,
    lang: str = "en",
    ui: dict | None = None,
) -> str:
    """`eyebrow` is the small uppercase line above the title (category · date · author),
    supplied by the caller from the document's metadata. `embed` renders for a frame
    inside another page (a directory's README on its category page): no eyebrow,
    no page padding, content flush left like the surrounding page. `ui` overrides
    the wrapper's few visible strings (see DEFAULT_UI)."""
    body = render_markdown_body(
        source, resolve, source_path=source_path, resolve_path=resolve_path, repo_url=repo_url
    )
    meta = _frontmatter(source)
    # Task-list checkboxes persist through DocState: per reader by default,
    # for everyone when the document says `task_scope: shared`.
    task_scope = "shared" if str(meta.get("task_scope", "")).lower() == "shared" else "me"
    tpl = _env.get_template("md_wrapper.html")
    return tpl.render(
        title=title,
        lang=lang,
        eyebrow="" if embed else eyebrow,
        embed=embed,
        has_h1=bool(_LEADING_H1.match(body)),
        body=body,
        pygments_css=PYGMENTS_CSS,
        needs_mermaid='class="mermaid"' in body,
        has_tasks="task-list-item-checkbox" in body,
        task_scope=task_scope,
        bridge_tag=BRIDGE_TAG,
        ui={**DEFAULT_UI, **(ui or {})},
    )


_HEAD_END = re.compile(r"</head\s*>", re.I)
_BODY_OPEN = re.compile(r"<body\b[^>]*>", re.I)


def prepare_html(content: str) -> str:
    """Inject the bridge so DocState exists before the document's own scripts run."""
    if BRIDGE_MARK in content:
        return content
    if m := _HEAD_END.search(content):
        return content[: m.start()] + BRIDGE_TAG + "\n" + content[m.start() :]
    if m := _BODY_OPEN.search(content):
        return content[: m.end()] + "\n" + BRIDGE_TAG + content[m.end() :]
    return BRIDGE_TAG + "\n" + content


_SCRIPT_STYLE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_MD_NOISE = re.compile(r"^[#>\-\*\s|]+", re.M)


def extract_text(content: str, kind: str) -> str:
    if kind == "html":
        text = _SCRIPT_STYLE.sub(" ", content)
        text = htmllib.unescape(_TAGS.sub(" ", text))
    else:
        text = _FENCE_SPLIT.sub(" ", content)
        text = _MD_NOISE.sub("", text)
        text = re.sub(r"[`*_\[\]()]", " ", text)
    return _WS.sub(" ", text).strip()


def html_title(content: str) -> str | None:
    if m := re.search(r"<title[^>]*>(.*?)</title>", content, re.I | re.S):
        return _WS.sub(" ", htmllib.unescape(_TAGS.sub("", m.group(1)))).strip() or None
    if m := re.search(r"<h1[^>]*>(.*?)</h1>", content, re.I | re.S):
        return _WS.sub(" ", htmllib.unescape(_TAGS.sub("", m.group(1)))).strip() or None
    return None


def html_description(content: str) -> str | None:
    if m := re.search(
        r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', content, re.I | re.S
    ):
        return htmllib.unescape(m.group(1)).strip() or None
    if m := re.search(r"<p[^>]*>(.*?)</p>", content, re.I | re.S):
        return _WS.sub(" ", htmllib.unescape(_TAGS.sub("", m.group(1)))).strip()[:160] or None
    return None
