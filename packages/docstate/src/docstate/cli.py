"""The `docstate` command.

docstate serve                      run the site
docstate publish FILE --category x  publish one file through the HTTP API
docstate import DIR                 import a repository checkout (directly into storage)
docstate migrate                    bring the database schema up to date
docstate check                      print the resolved configuration and probe the storage
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from collections import Counter
from pathlib import Path


def _cmd_serve(args: argparse.Namespace) -> int:
    if args.host:
        os.environ["DOCSTATE_HOST"] = args.host
    if args.port:
        os.environ["DOCSTATE_PORT"] = str(args.port)
    if args.mcp:
        os.environ["DOCSTATE_MCP"] = "true"
    import uvicorn

    from docstate.settings import get_settings

    s = get_settings()
    reload_dirs = None
    if args.reload:
        here = Path(__file__).resolve().parent
        reload_dirs = [str(here)]
        mcp_pkg = here.parent / "docstate_mcp"
        if mcp_pkg.is_dir():
            reload_dirs.append(str(mcp_pkg))
    uvicorn.run(
        "docstate.server.app:app",
        host=s.host,
        port=s.port,
        reload=args.reload,
        reload_dirs=reload_dirs,
        log_level=s.log_level.lower(),
    )
    return 0


def _cmd_publish(args: argparse.Namespace) -> int:
    import httpx

    from docstate.core.render import html_title

    path = Path(args.file)
    text = path.read_text(encoding="utf-8")
    kind = "html" if path.suffix.lower() in (".html", ".htm") else "md"
    title = args.title
    if not title:
        if kind == "html":
            title = html_title(text)
        else:
            m = re.search(r"^#\s+(.+?)\s*$", text, re.M)
            title = m.group(1).strip() if m else None
    title = title or path.stem
    payload = {
        "title": title,
        "content": text,
        "kind": kind,
        "category": args.category,
        "slug": args.slug,
        "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
        "label": args.label,
        "summary": args.summary,
        "status": args.status,
        "source_path": args.source_path,
        "dry_run": args.dry_run,
    }
    headers = {}
    if args.token:
        headers["X-Docstate-Token"] = args.token
    if args.author:
        headers["X-Docstate-Author"] = args.author
    r = httpx.post(f"{args.url.rstrip('/')}/api/publish", json=payload, headers=headers, timeout=60)
    if r.status_code != 200:
        print(f"publish failed: {r.status_code} {r.text}", file=sys.stderr)
        return 1
    data = r.json()
    if data["outcome"] == "dry_run":
        print("dry run; the site would flag:" if data["warnings"] else "dry run: no warnings")
    else:
        print(f"{data['outcome']:12s} v{data['version']}  {data['url']}")
    for w in data.get("warnings") or []:
        print(f"  warning: {w}")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    from docstate.core import importer
    from docstate.server.deps import get_storage
    from docstate.settings import get_settings

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"{root} is not a directory", file=sys.stderr)
        return 1
    storage = get_storage()
    storage.init()
    store = storage.docs
    tz = get_settings().zone
    stats: Counter = Counter()
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if not importer.wanted(rel) or (args.only and not rel.startswith(args.only)):
            continue
        if p.stat().st_size < importer.MIN_BYTES:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            stats["skipped"] += 1
            continue
        # frontmatter or filename dates beat the file's mtime for the timeline
        meta = importer.md_meta(rel, text) if importer.kind_of(rel) == "md" else None
        has_date = bool(
            (meta and (meta.updated or meta.created)) or importer.parse_date(Path(rel).stem)
        )
        mtime = dt.datetime.fromtimestamp(p.stat().st_mtime, dt.UTC).replace(tzinfo=None)
        result = importer.import_file(
            store, rel, text, author=args.author, committed_at=None if has_date else mtime, tz=tz
        )
        stats[result.outcome] += 1
        if args.verbose:
            print(f"{result.outcome:12s} {rel} -> /d/{result.doc.slug}")
        if args.limit and sum(stats.values()) >= args.limit:
            break
    print(dict(stats))
    return 0


def _cmd_migrate(_args: argparse.Namespace) -> int:
    from docstate.server.deps import get_storage

    storage = get_storage()
    storage.init()
    print(f"schema up to date: {storage.describe()}")
    return 0


def _cmd_check(_args: argparse.Namespace) -> int:
    from docstate.core.models import DocQuery
    from docstate.server.deps import get_storage
    from docstate.settings import get_settings
    from docstate.storage import StorageError

    s = get_settings()
    print(f"site_title      {s.site_title}")
    print(f"base_url        {s.public_base_url}")
    print(f"lang / tz       {s.lang} / {s.tz}")
    print(
        f"auth_mode       {s.auth_mode}"
        + (f" (header {s.auth_header})" if s.auth_mode == "header" else "")
    )
    print(f"allowed_domains {s.allowed_domains or '(any)'}")
    print(
        f"api_tokens      {', '.join(s.api_token_map.values()) or '(none: only fake mode is trusted)'}"
    )
    print(f"mcp in-process  {'on' if s.mcp else 'off'}")
    print(f"write-back      {'on: ' + s.github_repo if s.repo_sync_enabled else 'off'}")
    storage = get_storage()
    print(f"storage         {storage.describe()}")
    try:
        storage.ping()
    except StorageError as exc:
        print(f"storage         FAILED: {exc}")
        return 1
    try:
        n = len(storage.docs.list(DocQuery(limit=100000)))
        print(f"documents       {n} live")
    except Exception as exc:  # schema missing, most likely
        print(f"documents       cannot count ({exc}); run `docstate migrate`")
        return 1
    if s.auth_mode == "fake" and not s.base_url.startswith(("http://localhost", "http://127.")):
        print("warning         auth_mode=fake outside localhost lets anyone pick an identity")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docstate", description=__doc__.strip().splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="run the site (uvicorn)")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--reload", action="store_true", help="restart on source changes")
    p.add_argument("--mcp", action="store_true", help="also mount the MCP endpoint at /mcp")
    p.set_defaults(func=_cmd_serve)

    p = sub.add_parser("publish", help="publish one Markdown or HTML file through the HTTP API")
    p.add_argument("file")
    p.add_argument("--category", required=True)
    p.add_argument("--title")
    p.add_argument("--slug")
    p.add_argument("--tags", default="", help="comma-separated")
    p.add_argument("--label")
    p.add_argument("--summary")
    p.add_argument("--status", choices=["draft", "review", "approved", "deprecated"])
    p.add_argument("--source-path", help="repository path to record for the version")
    p.add_argument("--author", default=os.environ.get("DOCSTATE_AUTHOR"))
    p.add_argument("--url", default=os.environ.get("DOCSTATE_URL", "http://localhost:8787"))
    p.add_argument("--token", default=os.environ.get("DOCSTATE_TOKEN"))
    p.add_argument("--dry-run", action="store_true", help="only run the pre-publish checks")
    p.set_defaults(func=_cmd_publish)

    p = sub.add_parser("import", help="import a directory of Markdown / HTML files into storage")
    p.add_argument("root")
    p.add_argument("--only", help="only paths under this prefix, e.g. guides/")
    p.add_argument("--limit", type=int)
    p.add_argument("--author", help="author for files whose frontmatter names none")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=_cmd_import)

    p = sub.add_parser("migrate", help="create or upgrade the database schema")
    p.set_defaults(func=_cmd_migrate)

    p = sub.add_parser("check", help="print the resolved configuration and probe the storage")
    p.set_defaults(func=_cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
