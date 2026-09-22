"""Reader identity for the three modes; see the package docstring."""

from __future__ import annotations

import hmac
import logging
import secrets

from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from docstate.settings import Settings, get_settings

log = logging.getLogger("docstate.auth")

COOKIE = "docstate_viewer"  # fake mode: the chosen demo identity
ANON_COOKIE = "docstate_anon"  # none mode: the per-browser id
ANON_PREFIX = "anon:"


def valid_email(email: str | None, domains: frozenset[str] | None = None) -> bool:
    """Looks like an address and, when domains are configured, is in one of them."""
    if not email or "@" not in email:
        return False
    local, _, domain = email.rpartition("@")
    if not local or "@" in local or not domain:
        return False
    domains = domains if domains is not None else get_settings().allowed_domain_set
    return not domains or domain.lower() in domains


def _secret_matches(presented: str | None, secret: str) -> bool:
    # `secret and presented` is load-bearing: compare_digest("", "") is True, so an
    # unset secret would otherwise authenticate every anonymous request.
    return bool(secret) and bool(presented) and hmac.compare_digest(presented, secret)


def _header_identity(request: Request, s: Settings) -> str | None:
    secret = s.auth_proxy_secret.get_secret_value()
    if secret and not _secret_matches(request.headers.get(s.auth_secret_header), secret):
        return None
    email = request.headers.get(s.auth_header, "")
    return email.lower() if valid_email(email) else None


def _fake_identity(request: Request, s: Settings) -> str | None:
    header = request.headers.get(s.author_header)
    if valid_email(header):
        return header.lower()
    cookie = request.cookies.get(COOKIE)
    if valid_email(cookie):
        return cookie.lower()
    viewers = s.demo_viewer_list
    return viewers[0] if viewers else None


def _anonymous_identity(request: Request) -> str | None:
    anon = getattr(request.state, "anon_id", None) or request.cookies.get(ANON_COOKIE)
    return f"{ANON_PREFIX}{anon}" if anon else None


def viewer_email(request: Request) -> str | None:
    """The reader's identity, or None when nobody is signed in."""
    s = get_settings()
    if s.auth_mode == "header":
        return _header_identity(request, s)
    if s.auth_mode == "none":
        return _anonymous_identity(request)
    return _fake_identity(request, s)


def require_viewer(request: Request) -> str:
    email = viewer_email(request)
    if email is None:
        raise HTTPException(401, "sign in required")
    return email


def is_anonymous(viewer: str | None) -> bool:
    return bool(viewer) and viewer.startswith(ANON_PREFIX)


def viewer_label(viewer: str | None, guest: str = "guest") -> str:
    """What the top bar shows: the local part of an address, or "guest"."""
    if not viewer or is_anonymous(viewer):
        return guest
    return viewer.split("@")[0]


class AnonymousIdMiddleware(BaseHTTPMiddleware):
    """In `none` mode every browser gets a random id cookie so per-reader state
    ("me" scope) still has somewhere to live. Nothing else reads it."""

    async def dispatch(self, request: Request, call_next):
        new_id = None
        if get_settings().auth_mode == "none" and not request.cookies.get(ANON_COOKIE):
            new_id = secrets.token_hex(8)
            request.state.anon_id = new_id
        response = await call_next(request)
        if new_id:
            response.set_cookie(
                ANON_COOKIE, new_id, httponly=True, samesite="lax", max_age=365 * 86400
            )
        return response


def check_startup(s: Settings) -> None:
    """Refuse configurations that would let anyone in; warn about risky ones."""
    if s.auth_mode == "header" and not s.auth_header.strip():
        raise RuntimeError("DOCSTATE_AUTH_MODE=header needs DOCSTATE_AUTH_HEADER")
    if s.auth_mode == "fake" and not s.base_url.startswith(("http://localhost", "http://127.")):
        log.warning(
            "DOCSTATE_AUTH_MODE=fake lets anyone pick any identity; "
            "use `header` behind a login proxy or `none` for a public site"
        )
