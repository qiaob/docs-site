"""Who is reading, who is calling.

Reader identity (`identity.py`) comes from the configured mode:

    none    anonymous; a per-browser id makes the "me" state scope work
    fake    demo identities switchable from the top bar (local development)
    header  a login proxy in front of the site puts the verified email in a
            header (Cloudflare Access, oauth2-proxy, Tailscale, a gateway of
            your own); an optional shared-secret header proves the request
            came through the proxy and not straight to the pod

Service callers (`tokens.py`) present a named API token; they act for the
author they forward. Permissions (`authorize.py`) are a hook: allow-all unless
an authorizer plugin is configured."""

from .authorize import ADMIN, PUBLISH, READ, allowed, require
from .identity import (
    ANON_COOKIE,
    COOKIE,
    AnonymousIdMiddleware,
    check_startup,
    is_anonymous,
    require_viewer,
    valid_email,
    viewer_email,
    viewer_label,
)
from .tokens import api_caller, caller

__all__ = [
    "ADMIN",
    "PUBLISH",
    "READ",
    "ANON_COOKIE",
    "COOKIE",
    "AnonymousIdMiddleware",
    "allowed",
    "api_caller",
    "caller",
    "check_startup",
    "is_anonymous",
    "require",
    "require_viewer",
    "valid_email",
    "viewer_email",
    "viewer_label",
]
