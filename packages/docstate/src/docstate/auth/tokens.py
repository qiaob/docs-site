"""Service-to-service calls: named API tokens.

    DOCSTATE_API_TOKENS="ci:3f9…,agent:a81…"

A caller presenting a configured token (in `X-Docstate-Token` or as a Bearer
token) is trusted: it has already authenticated the person it acts for, so the
author is taken from the forwarded author header, else from the fallback the
endpoint gives, else the token's name. A wrong token is refused. With no tokens
configured, only local `fake` runs count as trusted."""

from __future__ import annotations

import hmac

from starlette.exceptions import HTTPException
from starlette.requests import Request

from docstate.settings import Settings, get_settings

from .identity import require_viewer, valid_email


def presented_token(request: Request, s: Settings) -> str | None:
    token = request.headers.get(s.api_token_header)
    if token:
        return token.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def token_name(presented: str | None, tokens: dict[str, str]) -> str | None:
    """The configured name of `presented`, compared in constant time against
    every token so timing does not reveal which one was close."""
    if not presented:
        return None
    found = None
    for token, name in tokens.items():
        if hmac.compare_digest(presented, token):
            found = name
    return found


def api_caller(request: Request, fallback: str | None = None) -> tuple[str, bool]:
    """(author, trusted) for a write endpoint."""
    s = get_settings()
    tokens = s.api_token_map
    forwarded = request.headers.get(s.author_header, "")
    if tokens:
        name = token_name(presented_token(request, s), tokens)
        if name is None:
            raise HTTPException(403, "missing or wrong service token")
        if valid_email(forwarded):
            author = forwarded.lower()
        else:
            author = (fallback or name).lower()
        return author, True
    trusted = s.auth_mode == "fake"
    if valid_email(forwarded):
        return forwarded.lower(), trusted
    return (fallback or "api@local").lower(), trusted


def caller(request: Request) -> tuple[str, bool]:
    """(identity, trusted) for a read endpoint: the trusted service when it
    presents a token, otherwise the signed-in reader."""
    s = get_settings()
    if s.api_token_map and presented_token(request, s) is not None:
        return api_caller(request)
    return require_viewer(request), False
