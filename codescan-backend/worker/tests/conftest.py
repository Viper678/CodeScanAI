"""Shared pytest setup for worker tests."""

from __future__ import annotations

import os

# Make sure tests don't accidentally point at a live Postgres just by importing
# settings. The unit tests don't open a session; integration tests overwrite
# this with a real URL.
os.environ.setdefault(
    "DATABASE_SYNC_URL",
    "postgresql+psycopg://codescan:codescan-dev-only-change-me@localhost:5432/codescan",
)
