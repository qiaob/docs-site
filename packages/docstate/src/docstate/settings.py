"""Runtime configuration.

Every option is an environment variable with the `DOCSTATE_` prefix. An
optional `docstate.toml` (path in `DOCSTATE_CONFIG`, default `./docstate.toml`)
holds the non-secret ones with the same names, lowercase, without the prefix,
and may carry `[profiles.<name>]` overlays selected with `DOCSTATE_PROFILE`:

    site_title = "Team docs"
    lang = "zh-CN"
    storage_url = "sqlite:///data/docstate.db"

    [profiles.prod]
    base_url = "https://docs.example.com"
    auth_mode = "header"

Precedence: environment > `.env` file > selected profile > file defaults > code
defaults. Secrets belong in the environment."""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class TomlProfileSource(PydanticBaseSettingsSource):
    """`docstate.toml` with the selected profile folded over the top-level keys."""

    def __init__(self, settings_cls: type[BaseSettings]):
        super().__init__(settings_cls)
        self._data = self._load()

    @staticmethod
    def _load() -> dict[str, Any]:
        path = Path(os.environ.get("DOCSTATE_CONFIG") or "docstate.toml")
        if not path.is_file():
            return {}
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        profiles = data.pop("profiles", {}) or {}
        profile = os.environ.get("DOCSTATE_PROFILE", "").strip()
        merged = {k: v for k, v in data.items() if not isinstance(v, dict)}
        if profile:
            if profile not in profiles:
                raise ValueError(f"DOCSTATE_PROFILE={profile!r} is not in {path}")
            merged.update(profiles[profile])
        return merged

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return {k: v for k, v in self._data.items() if k in self.settings_cls.model_fields}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCSTATE_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlProfileSource(settings_cls),
            file_secret_settings,
        )

    # --- storage -------------------------------------------------------------
    # Full URL, or PostgreSQL components (what most secret stores hand out).
    storage_url: str = "sqlite:///data/docstate.db"
    state_url: str = ""  # empty: state lives in the same database
    db_host: str = ""
    db_port: int = 5432
    db_user: str = ""
    db_password: SecretStr = SecretStr("")
    db_name: str = ""
    # Sharing a database with other applications: a table-name prefix, or (when
    # the role may create schemas) an own schema. Both ignored for SQLite.
    db_table_prefix: str = ""
    db_schema: str = ""
    auto_migrate: bool = True  # run migrations at startup; off = `docstate migrate` by hand

    # --- site ----------------------------------------------------------------
    site_title: str = "Docstate"
    lang: str = "en"  # UI language: en | zh-CN
    host: str = "0.0.0.0"
    port: int = 8787
    base_url: str = "http://localhost:8787"
    # repository-relative links to files that are not published documents point
    # here (e.g. https://github.com/org/docs/blob/main); empty leaves them as written
    source_repo_url: str = ""
    tz: str = "UTC"
    log_level: str = "INFO"

    # --- reader identity -----------------------------------------------------
    #   none    anonymous readers; "me" state is per browser
    #   fake    demo identities switchable from the top bar (local development)
    #   header  trust the email header of a login proxy in front of the site
    #           (Cloudflare Access, oauth2-proxy, Tailscale, your gateway); an
    #           optional shared secret proves the request came through it
    auth_mode: Literal["none", "fake", "header"] = "fake"
    auth_header: str = "X-Forwarded-Email"
    auth_secret_header: str = "X-Docstate-Proxy-Secret"
    auth_proxy_secret: SecretStr = SecretStr("")
    allowed_domains: str = ""  # comma-separated email domains; empty = any
    demo_viewers: str = "alice@example.com,bob@example.com,carol@example.com"
    login_url: str = ""  # where a signed-out reader is sent (header mode)
    logout_url: str = ""  # shown in the top bar when set
    authorizer: str = ""  # name of a `docstate.authorizer` entry point; empty = everyone may

    # --- service-to-service --------------------------------------------------
    # Named tokens for trusted callers (CI, the MCP server, other services):
    # "ci:abc123,agent:def456" or a bare token (named "api"). A trusted caller
    # publishes as the author it forwards in the author header.
    api_tokens: str = ""
    api_token_header: str = "X-Docstate-Token"
    author_header: str = "X-Docstate-Author"

    # --- limits --------------------------------------------------------------
    max_doc_bytes: int = 5 * 1024 * 1024
    max_state_bytes: int = 64 * 1024

    # --- MCP (in-process mount; the standalone server is the docstate-mcp package)
    mcp: bool = False
    mcp_author: str = "mcp@localhost"  # author when no token names one (local runs)
    mcp_source_root: str = ""  # `path=` publishing reads files under here; empty = off

    # --- GitHub write-back (optional integration) ---------------------------
    github_repo: str = ""  # owner/name; empty = write-back off
    github_branch: str = "main"
    github_api_url: str = "https://api.github.com"
    github_token: SecretStr = SecretStr("")
    github_app_id: str = ""
    github_app_private_key: SecretStr = SecretStr("")
    repo_sync_mode: Literal["direct", "dispatch"] = "direct"
    github_dispatch_workflow: str = "sync-from-docstate.yml"
    repo_sync_skip_categories: str = ""
    repo_sync_max_docs: int = 50
    repo_sync_timeout_seconds: float = 30.0

    # --- derived -------------------------------------------------------------
    @property
    def database_url(self) -> str:
        """The SQLAlchemy URL: components win when a host is given; bare
        postgres:// URLs are pointed at the psycopg 3 driver."""
        if self.db_host:
            pw = quote(self.db_password.get_secret_value(), safe="")
            user = quote(self.db_user, safe="")
            return f"postgresql+psycopg://{user}:{pw}@{self.db_host}:{self.db_port}/{self.db_name}"
        return normalize_db_url(self.storage_url)

    @property
    def state_database_url(self) -> str:
        return normalize_db_url(self.state_url) if self.state_url else ""

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    @property
    def allowed_domain_set(self) -> frozenset[str]:
        return frozenset(d.strip().lower() for d in self.allowed_domains.split(",") if d.strip())

    @property
    def demo_viewer_list(self) -> list[str]:
        return [v.strip() for v in self.demo_viewers.split(",") if v.strip()]

    @property
    def api_token_map(self) -> dict[str, str]:
        """token -> name."""
        out: dict[str, str] = {}
        for item in self.api_tokens.split(","):
            item = item.strip()
            if not item:
                continue
            name, sep, token = item.partition(":")
            if not sep:
                name, token = "api", name
            if token:
                out[token.strip()] = name.strip() or "api"
        return out

    @property
    def repo_sync_enabled(self) -> bool:
        has_credential = bool(self.github_token.get_secret_value()) or bool(
            self.github_app_id and self.github_app_private_key.get_secret_value()
        )
        return bool(self.github_repo.strip()) and has_credential

    @property
    def repo_sync_skip_list(self) -> frozenset[str]:
        return frozenset(
            p.strip().strip("/").lower()
            for p in self.repo_sync_skip_categories.split(",")
            if p.strip()
        )

    @property
    def public_base_url(self) -> str:
        return self.base_url.rstrip("/")


def normalize_db_url(url: str) -> str:
    from docstate.storage.sql.store import normalize_url

    return normalize_url(url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    """Tests only."""
    get_settings.cache_clear()
