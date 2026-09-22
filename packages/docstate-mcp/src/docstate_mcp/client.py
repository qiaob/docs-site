"""A thin asynchronous client for the Docstate HTTP API. The MCP tools call
this and nothing else, so the same server works against a remote site (over
HTTPS with a token) and in-process (through an ASGI transport)."""

from __future__ import annotations

from typing import Any

import httpx


class DocstateError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class DocstateClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        author: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
        token_header: str = "X-Docstate-Token",
        author_header: str = "X-Docstate-Author",
    ):
        headers = {}
        if token:
            headers[token_header] = token
        if author:
            headers[author_header] = author
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self.base_url, headers=headers, transport=transport, timeout=timeout
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = await self._http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise DocstateError(f"cannot reach {self.base_url}: {exc}") from exc
        if r.status_code >= 400:
            detail = ""
            try:
                detail = str(r.json().get("error") or "")
            except ValueError:
                detail = r.text[:300]
            raise DocstateError(f"{method} {path} -> {r.status_code}: {detail}", r.status_code)
        return r.json() if r.content else None

    # --- writes
    async def publish(self, payload: dict) -> dict:
        return await self._call("POST", "/api/publish", json=payload)

    async def check(self, payload: dict) -> dict:
        return await self._call("POST", "/api/publish", json={**payload, "dry_run": True})

    async def update_meta(self, slug: str, **fields: Any) -> dict:
        return await self._call("PATCH", f"/api/docs/{slug}", json=fields)

    async def archive(self, slug: str) -> dict:
        return await self._call("POST", f"/api/docs/{slug}/archive")

    # --- reads
    async def list(self, **params: Any) -> list[dict]:
        clean = {k: v for k, v in params.items() if v is not None}
        return await self._call("GET", "/api/docs", params=clean)

    async def search(self, q: str, limit: int = 50) -> list[dict]:
        return await self._call("GET", "/api/search", params={"q": q, "limit": limit})

    async def get(
        self, slug: str, version: int | None = None, include_content: bool = False
    ) -> dict:
        params: dict[str, Any] = {}
        if version:
            params["version"] = version
        if include_content:
            params["content"] = "1"
        return await self._call("GET", f"/api/docs/{slug}", params=params)

    async def versions(self, slug: str) -> list[dict]:
        return await self._call("GET", f"/api/docs/{slug}/versions")

    async def categories(self) -> list[dict]:
        return await self._call("GET", "/api/categories")
