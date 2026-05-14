"""Generate the deterministic sample repo zip used by the Playwright suite.

The zip lands at ``codescan-frontend/e2e/fixtures/tiny_repo.zip`` and is ignored by
git so the literal credential pattern below never enters source control —
gitleaks runs on diffs, and the in-zip text would otherwise trigger.

The repo contents are intentionally tiny but cover all three scan types:
    * ``src/config.py`` — a hardcoded API-key shaped credential (security)
    * ``src/main.py``   — a probable null-deref / unguarded attribute
                          (bug-report)
    * ``src/notes.txt`` — a TODO line (default keyword scan)

Run directly (``python build_sample_zip.py``) or have Playwright's
``globalSetup`` invoke it via ``python3``. Idempotent — overwrites the
existing zip in place.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent / "tiny_repo.zip"

# Fake-shaped Google AI API key — assembled at build time so the literal never
# lives in source. Pattern matches ``AIzaSy[A-Za-z0-9_-]{33}`` exactly.
_FAKE_KEY = "AIza" + "Sy" + "A" * 33


CONFIG_PY = f'''"""Service config — DO NOT use real credentials here."""

API_KEY = "{_FAKE_KEY}"
DEFAULT_TIMEOUT_S = 5
'''


MAIN_PY = '''"""Entry point — wires up the worker."""

from typing import Optional


def lookup_user(users, name):
    # Returns None when the user is missing; the caller below forgets to guard.
    found = users.get(name)
    return found


def greet(users, name):
    user = lookup_user(users, name)
    # Possible null deref — `user` may be None and `.full_name` would crash.
    return "Hello, " + user.full_name


if __name__ == "__main__":
    print(greet({}, "world"))
'''


NOTES_TXT = """\
Release notes for 0.1.0:

- Added basic user lookup helpers.
- TODO: harden config loader so it reads from env, not literals.
- Wire up retries for the upstream API.
"""


README_MD = """\
# Sample Repo

A tiny fixture used by the Playwright e2e suite. Three files, three findings.
"""


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # All entries live under ``sample-repo/`` so the worker's extraction
        # produces a single top-level dir matching the upload's display name.
        zf.writestr("sample-repo/README.md", README_MD)
        zf.writestr("sample-repo/src/config.py", CONFIG_PY)
        zf.writestr("sample-repo/src/main.py", MAIN_PY)
        zf.writestr("sample-repo/src/notes.txt", NOTES_TXT)
    print(f"wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
