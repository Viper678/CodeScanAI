# Contributing

Code conventions for CodeScan. Read once; live them.

---

## Python (api + worker)

- **Version:** 3.12+.
- **Type hints:** required on all public functions, methods, and module-level globals. `mypy --strict`-friendly.
- **Format:** `black` (default settings, line length 100).
- **Lint:** `ruff` with the rule set in `pyproject.toml`. Notable rules enforced: `B`, `S` (security), `SIM`, `RET`, `RUF`. `# noqa` requires a comment explaining why.
- **Imports:** absolute within an app (`from app.core.config import settings`), no relative imports beyond one level.
- **Async:** every API handler is `async def`. SQLAlchemy uses `AsyncSession`. Don't mix sync DB calls in the API.
- **Errors:** `raise HTTPException(status_code=..., detail=...)` only at the router boundary. Inside services, raise typed exceptions defined in `app.core.exceptions`. A central exception handler converts them to the standard error envelope.
- **No bare `except:`** — always specify the exception type. `except Exception:` requires a `# justify:` comment.
- **No `print`** — use the logger.
- **Docstrings:** Google-style on services and complex helpers. Routers, schemas, and models are largely self-documenting.

### Module layout (api)

```
apps/api/app/
├── main.py                  # FastAPI app factory
├── core/
│   ├── config.py            # Settings via pydantic-settings
│   ├── db.py                # engine, session, base
│   ├── security.py          # password, jwt
│   ├── deps.py              # get_db, get_current_user
│   ├── exceptions.py        # typed app exceptions
│   └── logging.py
├── models/                  # SQLAlchemy
│   ├── user.py
│   ├── upload.py
│   ├── file.py
│   ├── scan.py
│   ├── scan_file.py
│   └── scan_finding.py
├── schemas/                 # Pydantic input/output
│   ├── auth.py
│   ├── upload.py
│   ├── scan.py
│   └── finding.py
├── repositories/            # All DB access goes through these
│   ├── base.py              # BaseRepo with user_id filter
│   ├── upload_repo.py
│   └── ...
├── services/                # Business logic, no FastAPI imports
│   ├── auth_service.py
│   ├── upload_service.py
│   ├── scan_service.py
│   └── ...
├── routers/                 # FastAPI routers (thin)
│   ├── auth.py
│   ├── uploads.py
│   ├── scans.py
│   └── health.py
└── tests/
```

### Module layout (worker)

```
apps/worker/worker/
├── celery_app.py
├── core/
│   ├── config.py
│   ├── db.py
│   └── logging.py
├── llm/
│   ├── client.py            # only place that imports google.genai
│   ├── retry.py
│   ├── chunker.py
│   ├── prompts/
│   │   └── v1/
│   │       ├── security.txt
│   │       └── bugs.txt
│   └── schemas.py           # Pydantic for LLM responses
├── scanners/
│   ├── base.py              # Scanner protocol
│   ├── security.py
│   ├── bugs.py
│   └── keywords.py
├── tasks/
│   ├── prepare_upload.py
│   ├── run_scan.py
│   └── cleanup.py
└── tests/
```

### Naming

- snake_case for modules, functions, variables.
- PascalCase for classes.
- SCREAMING_SNAKE for constants and env-keys.
- Private-by-convention: leading underscore.
- DB columns are snake_case; model attributes mirror them exactly.

---

## TypeScript (web)

- **Strict mode** in `tsconfig.json`: `strict: true`, `noUncheckedIndexedAccess: true`.
- **Format:** `prettier`, single quotes, semicolons.
- **Lint:** `eslint` with `@typescript-eslint`, `react-hooks`, `tailwindcss` plugin.
- **No `any`** without `// reason:` comment.
- **No default exports** in shared modules — named exports for refactor safety. Pages / route components in Next.js are the exception (App Router requires `default export` for `page.tsx`).
- **API client:** all server calls go through `lib/api/*` — never `fetch` from a component. Generated types from OpenAPI live in `lib/api/types.gen.ts` and are regenerated via `pnpm gen:api`.
- **State:**
  - Server state → TanStack Query. Cache key conventions: `['scans']`, `['scans', id]`, `['scans', id, 'findings', filters]`.
  - Client state (UI-only) → Zustand stores under `lib/stores/`. Keep stores small and per-feature.
  - **Never** put server data in Zustand.
- **Components:**
  - One component per file unless tightly coupled.
  - Co-locate styles via Tailwind classes; no `.module.css` unless dynamic.
  - Composition over prop-drilling: pass children, not a hundred props.
- **Forms:** `react-hook-form` + `zod` resolver. Schemas in `lib/schemas/*`.

### Tailwind / shadcn

- Pull in shadcn components via the CLI on first use; they live in `components/ui/`.
- Don't override shadcn tokens globally; extend via the theme file.
- Use the design tokens from `UI_DESIGN.md` everywhere — no ad-hoc hex codes.

---

## Git hygiene

- Pre-commit hooks (installed by `make setup`):
  - black, ruff, mypy (changed files), prettier, eslint, gitleaks.
- Commits should pass the pre-commit hooks. Force-pushing to fix history during a feature branch is fine.
- No commits with a personal email if working on a shared account; configure `git config user.email` to your project email.

---

## Documentation

- If you change a public API, update `docs/API.md` in the same PR.
- If you change the DB shape, update `docs/SCHEMA.md` in the same PR.
- If you add a new scan type, update `docs/SCAN_RULES.md` in the same PR with the prompt and schema.
- New env vars → `docs/DEPLOYMENT.md` and `.env.example` in the same PR.

---

## Things we do not do

- We do not sprinkle TODO comments without a linked issue and a name.
- We do not add commented-out code; delete it (git remembers).
- We do not write generic utility folders (`utils/`, `helpers/`). Put helpers next to what uses them, or in a feature module.
- We do not add a dependency to do something Python or TypeScript stdlib does well.
- We do not write unit tests against frameworks (no "test that FastAPI returns JSON").
- We do not optimize prematurely. Profile first; the LLM call is almost always the bottleneck.
