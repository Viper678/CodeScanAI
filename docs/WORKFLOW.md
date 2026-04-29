# Workflow

This is the document the **AI agents must read before touching code.** It defines how to claim work, branch, build, test, and merge. Deviating from this gets PRs rejected.

---

## 0. Read these first

In order:
1. `README.md` (this repo)
2. `docs/ARCHITECTURE.md`
3. `docs/SCHEMA.md` and `docs/API.md`
4. `docs/TASKS.md` (pick a task)
5. `docs/CONTRIBUTING.md` (code style)
6. The task-specific docs (`FILE_HANDLING.md` if doing T2.x, `SCAN_RULES.md` if doing T3.3+, etc.)

If you cannot answer "what does this task touch and which interfaces it must respect?" don't start coding.

---

## 1. Branching

We use **trunk-based-ish** with short-lived feature branches.

- `main` — protected. Always deployable. No direct pushes.
- `feature/<task-id>-<slug>` — your branch. One task per branch.
  - Examples: `feature/T2.5-directory-tree`, `feature/T3.3-gemma-client`.
- `fix/<short-slug>` — small bug fixes not tied to a task.
- `chore/<short-slug>` — non-functional changes (docs, deps).

Rules:
- Branch off the latest `main`.
- Rebase onto `main` before opening the PR (no merge commits in feature branches).
- One task = one branch = one PR. If your work grows beyond a task, **open a second PR**, don't pile on.

---

## 2. Per-task workflow (the loop you must follow)

```
0. Pick task from TASKS.md → claim it on the project board (or in PR title)
1. git checkout main && git pull
2. git checkout -b feature/<task-id>-<slug>
3. Read all referenced docs for the task
4. Plan: write a 5-line plan as the first commit message body or as a PR description draft
5. Implement, in small commits
6. Run the full pre-merge gate locally (see §4)
7. Push, open PR (template below), self-review the diff
8. Address review, rebase, re-run gate
9. Merge via "Squash and merge" with a conventional-commit-formatted title
10. Delete the branch
```

Do **not** skip step 4 (planning). Even one paragraph is fine.

---

## 3. Commit conventions

Conventional Commits, lowercase scope:

```
<type>(<scope>): <subject>

<optional body>

<optional footer>
```

- `type` ∈ `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `build`, `ci`.
- `scope` ∈ `api`, `worker`, `web`, `infra`, `docs`, `auth`, `uploads`, `scans`, `tree`, etc.
- Subject: imperative, ≤ 72 chars, no trailing period.

Examples:
```
feat(uploads): accept zip and validate against zip-bomb heuristics
fix(api): return 403 not 404 when user requests another user's upload
test(worker): add fixtures for malformed zips
```

Squash-merge title on PRs follows the same format.

---

## 4. Pre-merge gate (must pass before opening PR)

Run from repo root:

```bash
make lint    # ruff + black --check + mypy + prettier --check + eslint
make test    # pytest (api + worker) + vitest (web)
make e2e     # playwright (only if you touched UI flows)
```

Plus, manually:
- Bring up `docker compose up --build` once and click through the flow you changed.
- For DB changes: confirm `alembic upgrade head` and `alembic downgrade -1` both work.

CI runs the same `make lint` and `make test` (and `make e2e` on the `e2e-required` label) on every PR. **PRs cannot be merged with a red CI.**

---

## 5. Pull request template

Every PR description must include:

```markdown
## Task
T<x.y> — <title>. Closes <issue link if any>.

## Summary
<2–5 sentences: what changed, why this approach.>

## Acceptance criteria
- [ ] AC 1 from TASKS.md
- [ ] AC 2 from TASKS.md
- [ ] All AC explicitly checked

## Tests
- Added: <list>
- Manual: <what you clicked through>

## Schema / API changes
- [ ] None
- [ ] Migration: <file>
- [ ] API contract: <endpoint(s) + before/after if breaking>

## Screenshots / GIFs (UI tasks)
<paste here>

## Risk / rollback
<one sentence on blast radius and how to revert>
```

PRs without the AC checklist explicitly checked are not reviewed.

---

## 6. Code review rules

Reviewers (human or AI):

- Block on: failing AC, missing tests, schema migration without rollback path, secrets in diff, breaking API change without versioning, raw SQL with string concat, missing user-id filter on a query, broad `except`.
- Comment but don't block: style nits if linters didn't catch them, naming preferences, future-proofing suggestions.
- Approve only when: AC checked, CI green, you have read the actual diff (not just the description).

Authors:
- Respond to every comment, even with "ack" or "won't fix because X".
- Force-push after rebase is fine; reviewers know.

---

## 7. Testing requirements per task type

| Task type            | Required tests                                                               |
| -------------------- | ---------------------------------------------------------------------------- |
| New API endpoint     | At least one happy-path integration test + one auth/authorization test + Pydantic schema validation tests |
| Worker task          | Unit test with mocked deps + integration test against compose Postgres/Redis |
| Frontend component   | Vitest for logic-bearing components (tree state machine, regex validator)    |
| Frontend page/flow   | Playwright e2e covering the new path                                          |
| Migration            | Apply + rollback both succeed in CI                                          |
| Bug fix              | A regression test that fails without the fix                                 |

Do not add tests just to inflate coverage. Test **behavior**, not implementation. Coverage target is "every branch with non-trivial logic," not a percentage.

---

## 8. Working with the database

- Never write SQL by string concatenation. Always SQLAlchemy ORM or parameterized core.
- Every read on an owned table includes `user_id == current_user.id`. Use the base repository class — do not bypass it.
- New tables / columns require a new alembic migration in the same PR.
- Don't `truncate`, `drop`, or change column types without explicit reviewer approval — use a rename pattern (add new, backfill, swap, drop old) over multiple PRs for prod-safe changes.

---

## 9. Working with the LLM

- All Gemma calls go through `apps/worker/worker/llm/client.py`. Don't import `google.genai` anywhere else.
- Prompts live in `apps/worker/worker/llm/prompts/v<N>/` as plain text. Do not template prompt instructions at call sites — only the user-prompt's data slots are templated.
- Bumping a prompt version is a separate PR.

---

## 10. Secrets, env, and config

- Never commit a real API key. CI fails on secrets via `gitleaks`.
- All config flows through `app.core.config.Settings` (api) and `worker.core.config.Settings` (worker), backed by env vars. New config = new field on Settings + new line in `.env.example`.

---

## 11. AI-agent-specific guidance

If you are an AI coding agent picking up tasks from this repo:

1. **Stay in your lane.** One task per branch. If you find a bug outside your task, file it (or open a separate `fix/` PR) — don't fold it in.
2. **Keep diffs reviewable.** PRs over 800 lines should be split. If a single task's diff is naturally larger (e.g. the tree component), call this out in the PR description and walk the reviewer through the structure.
3. **Don't invent schema or API.** If you need a new field/endpoint not in `SCHEMA.md` / `API.md`, **open a PR that updates the docs first**, get it approved, then implement.
4. **No side-quests in lockfiles.** If a dependency upgrade isn't required for the task, leave it. Lockfile churn must be intentional.
5. **Read failing tests; don't disable them.** If a test is wrong, fix the test in a separate `fix/` PR with justification. Never skip with `pytest.skip` or `it.skip` to make CI green.
6. **State assumptions in the PR body.** If a doc was ambiguous and you made a call, write down the call you made.
7. **No new top-level dependencies without justification.** If you can do it in stdlib in 30 lines, do that.

---

## 12. Definition of done

A task is done when:
- All ACs in `TASKS.md` are checked.
- CI is green.
- One human (or one AI reviewer + one human spot-check) has approved.
- Squash-merged into `main`.
- The branch is deleted.
- `TASKS.md` is updated only if the task was meaningfully redefined (otherwise leave it alone — the merge is the record).
