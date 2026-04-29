# File Handling

This is the most security-sensitive part of the app. Read carefully.

---

## Upload limits

| Limit                         | Value     | Where enforced              |
| ----------------------------- | --------- | --------------------------- |
| Max zip size                  | 100 MB    | API + reverse proxy         |
| Max single loose file size    | 50 MB     | API                         |
| Max loose files per upload    | 50        | API                         |
| Max uncompressed total size   | 500 MB    | Worker (during extraction)  |
| Max files in archive          | 20,000    | Worker                      |
| Max single file size to scan  | 1 MB      | Worker (excluded if larger) |
| Max nesting depth             | 20        | Worker                      |

If any of these are exceeded the upload moves to `failed` with a clear `error` message.

---

## Allowed upload types

A whitelist (not blacklist) for `kind=loose`. Source-code-like extensions only. The full list lives in `apps/api/app/core/file_types.py` (one source of truth, also imported by worker).

Examples:
```
.py .pyi .ipynb
.js .jsx .ts .tsx .mjs .cjs
.java .kt .scala .groovy
.go .rs
.rb .php
.c .h .cpp .hpp .cc .hh .cxx
.cs .fs .vb
.swift .m .mm
.sh .bash .zsh .fish .ps1
.sql
.html .htm .css .scss .less .vue .svelte
.json .yaml .yml .toml .ini .env (warning shown)
.md .rst .txt
.dockerfile (no ext) .tf .hcl
```

For `kind=zip`, we accept `.zip` MIME `application/zip`. Inside the zip we use the same whitelist when deciding `is_excluded_by_default` — but we do **not** reject the upload over unrecognized extensions, we just exclude them by default.

---

## Zip extraction safety

Implemented in `worker.tasks.prepare_upload`. Order matters:

1. **Pre-flight via `zipfile.ZipFile`:**
   - Iterate `infolist()` and reject if any:
     - `is_dir()` count > 5,000
     - regular file count > 20,000
     - `file_size` (uncompressed) > 50 MB for any single entry
     - sum of `file_size` > 500 MB
     - any entry has compression ratio > 100:1 (zip bomb heuristic)
2. **Path traversal guard:** for every entry, compute `os.path.normpath(entry.filename)` and reject the upload if the result starts with `..` or is absolute or contains a backslash (Windows paths).
3. **Extraction:** to `/data/extracts/<upload_id>/` using `Path` joined and re-resolved against the extract root; `assert resolved.is_relative_to(extract_root)` per file. Any failure → abort + cleanup.
4. **Symlink policy:** **never** extract symlinks. If `entry.create_system == 3` and the file mode indicates symlink, skip with a logged warning. Python's `ZipFile.extract` does not extract symlinks as symlinks by default (writes them as regular files containing the target path) but we still skip — those text files would be misleading and pollute the index.

Use `zipfile` from stdlib. If we ever support `.tar.gz`, switch to `tarfile.open(..., format=tarfile.PAX_FORMAT)` with the same safety pass — and explicitly use `extractall(filter='data')` on Python 3.12+.

---

## Tree building

After extraction, the worker walks `extract_path` once and produces a `files` row per regular file. Directories are **not** stored — they're inferred from `path` / `parent_path` on read.

For each file:

```python
@dataclass
class FileMeta:
    path: str               # forward slashes, relative to extract root
    parent_path: str        # dirname(path), '' for root files
    name: str               # basename(path)
    size_bytes: int
    sha256: str             # for dedup + cache
    language: str | None    # detected
    is_binary: bool
    is_excluded_by_default: bool
    excluded_reason: str | None  # see enum below
```

### Binary detection

Read first 8 KB. Heuristic:
- If a NUL byte is present → binary.
- Else if non-text byte ratio > 30% (chars outside `0x09, 0x0A, 0x0D, 0x20-0x7E, 0x80-0xFF UTF-8 valid sequences`) → binary.

Use `chardet` only if heuristic is uncertain. Don't use libmagic (extra system dep).

### Language detection

Two-stage:
1. Extension-based map (`.py → python`, etc.). Source of truth in `file_types.py`. Covers ~95% of cases.
2. For shebang-only files (no extension): read first line, match `#!/usr/bin/env python` etc.

If still unknown → `language = null` and the file is treated as plain text by the scanner (still scanned, weaker prompt context).

---

## Default exclusion rules

A file gets `is_excluded_by_default=true` if **any** rule matches. `excluded_reason` is the first matching rule.

In priority order:

| Reason             | Matches                                                                                   |
| ------------------ | ----------------------------------------------------------------------------------------- |
| `oversize`         | `size_bytes > 1 MB`                                                                      |
| `binary`           | binary detection result                                                                  |
| `vendor_dir`       | path segment in `{node_modules, vendor, third_party, .venv, venv, env, virtualenv, __pycache__, .pytest_cache, .mypy_cache, .ruff_cache, .tox, target, build, dist, out, .next, .nuxt, .gradle, .cargo, deps, _deps, bower_components}` |
| `vcs_dir`          | path segment in `{.git, .svn, .hg, .bzr}`                                                |
| `ide_dir`          | path segment in `{.idea, .vscode, .vs, .fleet, .DS_Store}`                               |
| `lockfile`         | basename in `{package-lock.json, yarn.lock, pnpm-lock.yaml, bun.lockb, poetry.lock, Pipfile.lock, composer.lock, Cargo.lock, Gemfile.lock, go.sum, mix.lock, gradle.lockfile}` |
| `build_artifact`   | extension in `{.pyc, .pyo, .class, .jar, .war, .o, .a, .so, .dylib, .dll, .exe, .obj, .lib, .map, .min.js, .min.css}` |
| `image`            | extension in `{.png, .jpg, .jpeg, .gif, .ico, .bmp, .tif, .tiff, .webp, .heic, .avif}`   |
| `font`             | extension in `{.ttf, .otf, .woff, .woff2, .eot}`                                         |
| `media`            | extension in `{.mp3, .mp4, .mov, .avi, .mkv, .wav, .flac, .ogg}`                         |
| `archive`          | extension in `{.zip, .tar, .gz, .bz2, .xz, .7z, .rar}`                                   |
| `dotfile`          | basename starts with `.` AND not in allowlist `{.env.example, .gitignore, .dockerignore}` (the allowlisted dotfiles still get scanned) |
| `unknown_ext`      | extension not in source-code whitelist AND not text-like                                  |

Notes:
- Path segment matching is case-insensitive on Windows-origin archives but case-sensitive otherwise. To stay simple: case-insensitive throughout.
- Dotfile `.env` (without `.example`) is **not excluded** — we want it scanned by the security scanner specifically because it often contains secrets the user shouldn't have committed.

---

## User overrides

The `is_excluded_by_default` flag is purely a UI default. The user's selection sent in `POST /scans { file_ids: [...] }` is the ground truth. The server still applies one **hard** filter: if a selected `file_id` resolves to a file whose `size_bytes > MAX_SCAN_FILE_SIZE` (1 MB), we **skip** it server-side and emit an `info` finding noting the skip. This protects token budget.

Users cannot override binary detection — binaries are dropped at scan time with `scan_files.status=skipped, error="binary"`.

---

## Tree presentation contract

The tree endpoint returns a flat list. The frontend constructs the visual tree. To make this fast and deterministic:

1. Sort entries by `path` lexicographically.
2. Group by `parent_path`.
3. For each parent_path with children, emit a directory node.
4. Recurse.

A directory's **default-excluded** state is `true` iff every leaf descendant is excluded by default. (Computed client-side, cached.)

Tri-state checkbox math:

```ts
function getDirState(dir): 'checked'|'unchecked'|'indeterminate' {
  const leaves = collectLeaves(dir);
  const selected = leaves.filter(f => selection.has(f.id)).length;
  if (selected === 0) return 'unchecked';
  if (selected === leaves.length) return 'checked';
  return 'indeterminate';
}
```

Toggling a directory:
- If currently `unchecked` or `indeterminate` → select all non-excluded descendants. (Excluded ones stay unselected unless user expands and toggles them individually — this matches user expectation.)
- If currently `checked` → deselect all descendants.

---

## File reads in the scan pipeline

Worker reads via:
```python
def safe_read(extract_root: Path, rel_path: str) -> str:
    p = (extract_root / rel_path).resolve()
    if not p.is_relative_to(extract_root.resolve()):
        raise SecurityError(f"escape attempt: {rel_path}")
    with p.open('rb') as f:
        data = f.read(MAX_SCAN_FILE_SIZE + 1)
    if len(data) > MAX_SCAN_FILE_SIZE:
        raise OversizeError()
    return data.decode('utf-8', errors='replace')
```

Decoded with `errors='replace'` so an exotic encoding doesn't kill the scan; the model handles `\ufffd` fine.

---

## Garbage collection

Daily Celery beat task (`cleanup_old_uploads`):
- Delete `extracts/<upload_id>/` and the raw zip for any upload whose `created_at < now - RETENTION_DAYS`.
- Cascade-delete the `uploads` row, which cascades to files / scans / findings.
- Configurable; default 30 days. **TODO:** confirm retention policy with product owner.
