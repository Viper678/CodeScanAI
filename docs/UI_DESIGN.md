# UI Design

## Design language

- **Visual tone:** clean, dense, developer-leaning. Think Linear / Vercel dashboard, not B2C SaaS.
- **Typography:** Inter for UI, JetBrains Mono for code snippets and paths.
- **Color system (Tailwind tokens, dark-mode-first):**
  - background: `zinc-950` (dark) / `zinc-50` (light)
  - surface: `zinc-900` / `white`
  - border: `zinc-800` / `zinc-200`
  - text: `zinc-100` / `zinc-900`
  - **accent: TODO — pick brand color.** Placeholder: `indigo-500`.
  - severity scale: `critical=red-500`, `high=orange-500`, `medium=amber-400`, `low=sky-400`, `info=zinc-400`
- **Component library:** shadcn/ui. Add only as needed; never pull in unused ones.
- **Density:** comfortable on desktop (1280+), responsive to tablet, gracefully degraded on mobile (login + read-only results only on mobile in v1).

---

## Layout

Persistent app shell once authenticated:

```
┌────────────────────────────────────────────────────┐
│  CodeScan logo │  search (v1.1)        avatar ▼    │ ← top bar
├──────────┬─────────────────────────────────────────┤
│ Scans    │                                          │
│ Uploads  │      page content                        │
│ Settings │                                          │
│          │                                          │
│ + New    │                                          │
└──────────┴─────────────────────────────────────────┘
```

Sidebar collapses to icon rail at < 1024px.

---

## Pages

### `/login` and `/register`
Centered card, email + password, link to the other. Inline error block on submit failure. No third-party auth in v1.

### `/dashboard` (= `/scans`)
- Header: "Scans" + "New scan" primary button.
- Empty state: friendly illustration, "Run your first scan" CTA.
- Table columns: name | upload | scan types (badges) | findings (severity dots) | status | created | actions (delete, re-run).
- Row click → `/scans/{id}`.
- Filter bar above table: status pill filter, scan-type filter, free-text search by name.
- Pagination: cursor-based, "Load more" button.

### `/uploads`
- Same shape as scans page but for uploads.
- Row click → upload detail with tree preview.
- Action: "Start scan" jumps into the wizard pre-filled with this upload.

### `/scans/new` — wizard

A 4-step horizontal stepper. Each step has Next / Back. Back never destroys state.

#### Step 1 — Upload
- Drag-and-drop zone (large) or click-to-browse.
- Accepts a single `.zip` or up to 50 loose source files.
- Shows file name, size, parses as it uploads.
- Progress bar during upload.
- Once uploaded, polls extraction status with a small spinner: "Extracting and indexing files… 1,842 files found, 312 scannable."
- "Next" enabled only when `uploads.status=ready`.

#### Step 2 — Select files (the most important screen)
- Left pane (70%): the **tree** with checkboxes.
- Right pane (30%): selection summary + filters.

**Tree behavior:**
- Rendered as virtualized list (TanStack Virtual) — must handle 10k+ nodes.
- Each row: `[checkbox] [chevron if dir] [icon] name [size, language pill]`.
- Checkbox states: unchecked / checked / **indeterminate** (some descendants checked).
- Clicking a directory checkbox cascades to all descendants; indeterminate parent state is computed on render.
- Excluded-by-default rows are visually de-emphasized (lower opacity, struck-through size) and unchecked. Hovering shows an "Excluded: vendor_dir — click to include" tooltip. Clicking the checkbox includes them anyway.
- Search box filters the tree (matches on substring of `path`); clears via Esc.
- Toolbar buttons: "Select all", "Deselect all", "Reset to defaults", "Show only selected".

**Right pane:**
- Big number: "247 of 312 files selected".
- Estimated tokens & cost (rough): "~480k tokens, ≈ $X" (see `SCAN_RULES.md` for cost calc).
- Warnings: "12 files exceed 256K context and will be split" / "3 files over 1MB will be skipped".

#### Step 3 — Scan configuration
- Three big toggle cards with checkboxes:
  - **Security scan** — short blurb, list of categories (injections, secrets, weak crypto…).
  - **Bug report scan** — short blurb (logic bugs, null derefs, leaks…).
  - **Keyword scan** — toggle reveals input section:
    - Comma-separated keywords or one per line.
    - "Case sensitive" toggle.
    - "Regex mode" toggle (with "Validate" check button — calls server to validate patterns).
- Optional: scan name field (defaults to `<upload> – <date>`).
- Advanced (collapsed): temperature slider (default 0.0), severity threshold filter ("Only show high+").

#### Step 4 — Confirm & start
- Read-only summary of all selections.
- "Start scan" primary button, "Back" secondary.
- On click → `POST /scans` → redirect to `/scans/{id}`.

### `/scans/{id}` — progress + results
- Header: scan name, status pill, scan-type badges, "Cancel" if running, "Re-run" if completed, "Export" dropdown.
- While `pending` / `running`:
  - Big progress bar `47/312`, ETA, throughput (files/min).
  - Live findings counter by severity (animates as findings arrive).
  - Tail log: scrolling list of recently scanned files with status icons.
- Once `completed`:
  - Severity summary cards (counts per severity, click to filter).
  - Findings table with columns: severity dot | file path | line | scan type | title.
  - Filters above table: severity, scan type, file path search.
  - Row click → expands inline with `message`, `recommendation`, and the **snippet** rendered with line numbers and the offending lines highlighted.
  - File path is also a link to `/uploads/{upload_id}/files/{file_id}` (read-only file viewer with all findings inline).

### `/uploads/{id}/files/{file_id}` — file viewer
- Monaco / CodeMirror read-only viewer with the file content.
- Findings shown as gutter markers + inline annotations.
- Sidebar lists findings in this file with click-to-jump.

### `/settings`
- Profile (email, change password — TODO confirm scope).
- API key management for Gemma — **server-managed only in v1**; user does not enter their own key.
- Active sessions / refresh tokens with revoke (nice to have for v1).

---

## Key components

### `<DirectoryTree />`
Props: `files: TreeFile[]`, `selected: Set<string>`, `onChange(set)`, `defaultExcluded: boolean`.
Internally builds the tree from flat paths, virtualizes, manages tri-state checkboxes. Pure controlled component.

### `<FindingsTable />`
Props: `scanId`, accepts filter props. Internally uses TanStack Query infinite scroll against `/scans/{id}/findings`. Supports row expansion.

### `<SeverityBadge />`, `<ScanTypeBadge />`, `<StatusPill />`
Trivial presentational components, but extracted so styling is consistent everywhere.

### `<UploadDropzone />`
Wraps a hidden input + drag handlers, shows progress via `XMLHttpRequest` (so we can get upload progress events that `fetch` doesn't expose).

### `<CodeViewer />`
Wraps CodeMirror 6. Read-only. Accepts `findings` to render gutter markers.

---

## Empty / loading / error states (every screen has all three)

- **Loading**: skeleton blocks where content will land. No spinners on full-page loads — skeletons only.
- **Empty**: short message + a primary action. No clip-art unless explicitly themed.
- **Error**: muted card with one-sentence cause + "Retry" or "Contact support" link. Never expose stack traces.

---

## Accessibility

- All interactive elements keyboard-reachable; focus rings visible (don't `outline:none` unless replaced).
- Tree supports arrow keys (up/down navigates rows, left/right collapses/expands, space toggles checkbox).
- Color is never the only signal (severity also has icon + label).
- Forms have proper labels; error messages associated via `aria-describedby`.
- Target WCAG 2.1 AA contrast.
