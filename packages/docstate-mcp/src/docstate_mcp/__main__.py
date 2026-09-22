"""`docstate-mcp`: run the MCP server against a Docstate site.

DOCSTATE_URL=https://docs.example.com DOCSTATE_TOKEN=... docstate-mcp
docstate-mcp --transport http --port 9000 --source-root ./docs
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .client import DocstateClient
from .server import build_server


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docstate-mcp", description=__doc__.strip().splitlines()[0])
    p.add_argument(
        "--url",
        default=os.environ.get("DOCSTATE_URL", "http://localhost:8787"),
        help="the Docstate site",
    )
    p.add_argument(
        "--token", default=os.environ.get("DOCSTATE_TOKEN"), help="API token configured on the site"
    )
    p.add_argument(
        "--author", default=os.environ.get("DOCSTATE_AUTHOR"), help="author recorded for publishes"
    )
    p.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("DOCSTATE_MCP_TRANSPORT", "stdio"),
    )
    p.add_argument("--host", default=os.environ.get("DOCSTATE_MCP_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("DOCSTATE_MCP_PORT", "9000")))
    p.add_argument(
        "--source-root",
        default=os.environ.get("DOCSTATE_MCP_SOURCE_ROOT"),
        help="confine path= publishing to this directory",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = DocstateClient(args.url, token=args.token, author=args.author)
    root = Path(args.source_root) if args.source_root else None
    if args.transport == "http" and root is None:
        print(
            "warning: --transport http without --source-root lets callers publish any readable file",
            file=sys.stderr,
        )
    mcp = build_server(client, source_root=root)
    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
