"""Process-wide storage handle, built from settings on first use."""

from __future__ import annotations

from functools import lru_cache

from docstate.settings import get_settings
from docstate.storage import Storage, open_storage


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    return open_storage(
        s.database_url,
        state_url=s.state_database_url,
        table_prefix=s.db_table_prefix,
        schema=s.db_schema,
    )


def reset_storage() -> None:
    """Tests only."""
    get_storage.cache_clear()
