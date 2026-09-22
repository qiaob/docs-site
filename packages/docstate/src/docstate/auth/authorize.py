"""Permissions. Three of them:

    read      open the site, read documents, save one's own state
    publish   publish and update through the API (as the forwarded author)
    admin     archive or re-file anyone's document

By default everyone who is signed in holds all three. To plug in your own
rules, publish an entry point in the `docstate.authorizer` group whose object
is `callable(principal: str, permission: str) -> bool` and name it in
`DOCSTATE_AUTHORIZER`."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from importlib.metadata import entry_points

from starlette.exceptions import HTTPException

from docstate.settings import get_settings

log = logging.getLogger("docstate.auth")

READ = "read"
PUBLISH = "publish"
ADMIN = "admin"

Authorizer = Callable[[str, str], bool]


@lru_cache
def _hook() -> Authorizer | None:
    name = get_settings().authorizer.strip()
    if not name:
        return None
    for ep in entry_points(group="docstate.authorizer"):
        if ep.name == name:
            return ep.load()
    raise RuntimeError(f"DOCSTATE_AUTHORIZER={name!r} is not an installed docstate.authorizer")


def allowed(principal: str, permission: str) -> bool:
    hook = _hook()
    return True if hook is None else bool(hook(principal, permission))


def require(principal: str, permission: str) -> None:
    if not allowed(principal, permission):
        raise HTTPException(403, f"{principal} does not have the {permission} permission")


def reset() -> None:
    """Tests only."""
    _hook.cache_clear()
