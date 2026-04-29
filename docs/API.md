# API Specification

Base URL (local): `http://localhost:8000/api/v1`

All non-auth endpoints require an authenticated session. JWT access token is sent as an httpOnly cookie named `cs_access`. Refresh token is `cs_refresh`. CSRF is mitigated via SameSite=Lax + custom header `X-Requested-With: codescan` required on mutating requests.

OpenAPI is auto-generated and served at `/docs` and `/openapi.json`.

---

## Conventions

### Error response

```json
{
  "error": {
    "code": "validation_error",
    "message": "human-readable message",
    "details": [
      { "loc": ["body", "email"], "msg": "value is not a valid email" }
    ]
  }
}
```

Codes (non-exhaustive): `validation_error`, `unauthorized`, `forbidden`, `not_found`, `conflict`, `payload_too_large`, `unprocessable_archive`, `rate_limited`, `internal_error`.

### Pagination

List endpoints return:
```json
{ "items": [...], "next_cursor": "opaque-string-or-null", "total": 123 }
```
Pass `?cursor=...&limit=...` (limit max 100, default 20).

### Timestamps

All timestamps are RFC3339 UTC: `2026-04-28T11:42:00Z`.

---

## Auth

### `POST /auth/register`

Request:
```json
{ "email": "user@example.com", "password": "min 12 chars" }
```
Response `201`:
```json
{ "id": "uuid", "email": "user@example.com" }
```
Sets `cs_access` and `cs_refresh` cookies.

Errors: `409 conflict` if email taken; `422 validation_error` for weak password.

### `POST /auth/login`
Request: same shape as register.
Response `200`: `{ "id": "uuid", "email": "..." }`. Sets cookies.
Errors: `401 unauthorized` (generic — never reveal which of email / password was wrong).

### `POST /auth/refresh`
No body. Reads `cs_refresh`, rotates it, returns new pair via cookies. `401` if invalid / revoked.

### `POST /auth/logout`
Revokes refresh token, clears cookies. `204`.

### `GET /auth/me`
`200`: `{ "id": "uuid", "email": "..." }`. `401` otherwise.

---

## Uploads

### `POST /uploads`
`multipart/form-data`:
- `file`: a single `.zip` **or** one of the allowed source extensions (see `FILE_HANDLING.md`).
- `kind`: `zip` or `loose` (server validates against actual file).

Multi-file loose upload sends multiple `file` parts; server treats them as a synthetic root and skips extraction.

Response `202`:
```json
{
  "id": "uuid",
  "status": "received",
  "kind": "zip",
  "original_name": "myrepo.zip",
  "size_bytes": 4823104
}
```
Server has accepted the upload and queued extraction. Poll `GET /uploads/{id}`.

Errors: `413 payload_too_large`, `415` (bad type), `422 unprocessable_archive` (corrupt zip).

### `GET /uploads/{id}`
Response `200`:
```json
{
  "id": "uuid",
  "status": "ready",
  "kind": "zip",
  "original_name": "myrepo.zip",
  "size_bytes": 4823104,
  "file_count": 1842,
  "scannable_count": 312,
  "created_at": "...",
  "error": null
}
```

### `GET /uploads/{id}/tree`
Returns the materialized tree for the upload. Response is a flat list; the frontend builds the tree:

```json
{
  "upload_id": "uuid",
  "root_name": "myrepo",
  "files": [
    {
      "id": "uuid",
      "path": "src/api/auth.py",
      "parent_path": "src/api",
      "name": "auth.py",
      "size_bytes": 4321,
      "language": "python",
      "is_binary": false,
      "is_excluded_by_default": false,
      "excluded_reason": null
    },
    {
      "id": "uuid",
      "path": "node_modules",
      "parent_path": "",
      "name": "node_modules",
      "size_bytes": 0,
      "language": null,
      "is_binary": false,
      "is_excluded_by_default": true,
      "excluded_reason": "vendor_dir"
    }
  ]
}
```

Directories are returned as entries with `language: null`, `is_binary: false`, and a `size_bytes` of the sum of children. The frontend renders directories purely from `parent_path` relationships of children — directory-level rows are emitted only for excluded vendor dirs we want to surface (so user can expand and override).

### `GET /uploads`
List user's uploads (paginated).

### `DELETE /uploads/{id}`
`204`. Cascades to files, scans, findings. Removes extracted files from disk.

---

## Scans

### `POST /scans`

```json
{
  "upload_id": "uuid",
  "name": "first pass",
  "scan_types": ["security", "bugs", "keywords"],
  "file_ids": ["uuid", "uuid"],
  "keywords": {
    "items": ["TODO", "HACK", "FIXME"],
    "case_sensitive": false,
    "regex": false
  },
  "model_settings": { "temperature": 0.0 }
}
```

Validation:
- `scan_types` is non-empty.
- `keywords.items` required and non-empty if `"keywords"` in `scan_types`.
- `file_ids` is non-empty, all belong to `upload_id`, all owned by user.
- File count cap: `MAX_FILES_PER_SCAN` (default 500). `422` over limit.

Response `202`:
```json
{ "id": "uuid", "status": "pending", "progress_done": 0, "progress_total": 312 }
```
Server enqueues `run_scan(scan_id)`.

### `GET /scans/{id}`
```json
{
  "id": "uuid",
  "name": "first pass",
  "upload_id": "uuid",
  "scan_types": ["security", "bugs"],
  "status": "running",
  "progress_done": 47,
  "progress_total": 312,
  "started_at": "...",
  "finished_at": null,
  "summary": {
    "by_severity": {"critical": 0, "high": 3, "medium": 12, "low": 41, "info": 8},
    "by_type": {"security": 18, "bugs": 46, "keywords": 0}
  }
}
```

### `GET /scans`
List user's scans (paginated, filterable by `?status=` and `?upload_id=`).

### `POST /scans/{id}/cancel`
`200` on success. Worker checks a cancellation flag between files and exits gracefully.

### `DELETE /scans/{id}`
`204`. Cascades to scan_files and findings.

### `GET /scans/{id}/findings`
Query params: `?severity=high,critical&scan_type=security&file_id=...&cursor=&limit=`

```json
{
  "items": [
    {
      "id": "uuid",
      "scan_type": "security",
      "severity": "high",
      "title": "SQL injection via string concatenation",
      "message": "...",
      "recommendation": "...",
      "file": {
        "id": "uuid",
        "path": "src/api/users.py"
      },
      "line_start": 42,
      "line_end": 44,
      "snippet": "...",
      "rule_id": "CWE-89",
      "confidence": 0.92
    }
  ],
  "next_cursor": null,
  "total": 87
}
```

### `GET /scans/{id}/export?fmt=json|csv`
Returns the file with appropriate content-type. CSV columns: `file_path, line_start, line_end, scan_type, severity, title, message, recommendation, rule_id`.

---

## Health

### `GET /healthz`
`200 {"status":"ok"}`. Verifies process is up. No auth required.

### `GET /readyz`
`200 {"status":"ok","db":"ok","redis":"ok"}` or `503` with which dependency failed. Used by docker-compose / orchestrator.

---

## Rate limits

- `POST /auth/login` and `POST /auth/register`: 5 requests per IP per minute (Redis-backed sliding window).
- `POST /uploads`: 10 per user per hour.
- `POST /scans`: 30 per user per hour.

`429 rate_limited` with `Retry-After` header.
