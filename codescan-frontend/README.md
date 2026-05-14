# CodeScan Frontend

Next.js 14 (App Router) UI for CodeScan. Talks to the backend exclusively over
HTTP via a server-side proxy at `app/api/v1/[...path]/route.ts` — the browser
only ever sees this origin, never the backend's. The proxy forwards the
session cookie / CSRF header through to FastAPI and streams the response
back.

## Quick start (development)

From this directory:

```bash
pnpm install
pnpm dev
```

Point `INTERNAL_API_URL` at a running backend (e.g. `http://localhost:8000/api/v1`
if you're running the backend natively, or `http://api:8000/api/v1` if you're
running it under docker-compose with the web container attached to the same
network).

Alternatively, from the monorepo root:

```bash
docker compose up --build
```

That brings up the frontend alongside `api + worker + postgres + redis` and
wires `INTERNAL_API_URL` through the compose network automatically. The UI is
reachable at <http://localhost:3000>.

## Key environment variables

- `INTERNAL_API_URL` — backend base URL. Read at **request time** (not at
  build time) so a single compiled image works across dev / UAT / prod
  without rebuilds. Default: `http://api:8000/api/v1` (the docker-compose
  service name).

The browser bundle has no API URL baked in — every backend call goes through
the Next.js server proxy.

## Make targets

Run these from the monorepo root:

- `make lint-web` — prettier + eslint + `tsc --noEmit`
- `make test-web` — vitest (component + hook tests)

The Playwright end-to-end suite has its own targets (`make e2e`, `make e2e-up`,
`make e2e-down`) that bring up a dedicated compose stack with mocked Gemma.

## Docs

Architecture, API contracts, and UI design notes live in the top-level
`docs/` directory:

- `docs/ARCHITECTURE.md` — system shape
- `docs/API.md` — HTTP contracts (consumed by the proxy + hooks)
- `docs/UI_DESIGN.md` — page / component design notes
- `docs/FLOW.md` — end-to-end user journey
- `docs/TESTING.md` — vitest + Playwright conventions

This README is intentionally short — orientation only, not a full guide.
