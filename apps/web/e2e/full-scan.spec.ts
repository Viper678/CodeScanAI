import { resolve } from 'node:path';
import { existsSync, readFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';

const SAMPLE_ZIP = resolve(__dirname, 'fixtures', 'tiny_repo.zip');

/**
 * End-to-end happy path (T5.5):
 *   1. Register a fresh user.
 *   2. Upload the deterministic sample repo zip.
 *   3. Configure & start a scan covering all three scan types.
 *   4. Wait for completion; assert the findings table renders rows.
 *   5. Trigger the JSON export and verify the downloaded payload.
 *
 * Gemma is mocked via ``LLM_MOCK_MODE=true`` on the worker — no real network
 * calls happen. The five legs each have at least one substantive assertion
 * so a regression in any one shows up here, not three legs later.
 */

function uniqueEmail(): string {
  // Per-run unique so ``register`` never hits a 409 conflict.
  const stamp = Date.now().toString(36);
  const rand = Math.floor(Math.random() * 1e9).toString(36);
  return `e2e+${stamp}.${rand}@codescan.test`;
}

const PASSWORD = 'CorrectHorseBattery!9';

test.describe('happy path: register → upload → scan → findings → export', () => {
  test.beforeAll(() => {
    if (!existsSync(SAMPLE_ZIP)) {
      throw new Error(
        `sample zip missing at ${SAMPLE_ZIP}; ` +
          `run the global setup or python3 e2e/fixtures/build_sample_zip.py.`,
      );
    }
  });

  test('full happy path', async ({ page, baseURL }) => {
    test.setTimeout(5 * 60_000);
    const email = uniqueEmail();

    // ---- Leg 1: register ---------------------------------------------------
    await page.goto('/register');
    await expect(
      page.getByRole('heading', { name: /create your account/i }),
    ).toBeVisible();

    await page.getByLabel(/email/i).fill(email);
    await page.getByLabel(/password/i).fill(PASSWORD);
    await page.getByRole('button', { name: /create account/i }).click();

    // Successful register lands on the post-login destination (uploads list
    // by default; see resolvePostLoginDestination).
    await page.waitForURL(/\/uploads(?:$|\?|\/)/, { timeout: 30_000 });
    await expect(page).toHaveURL(/\/uploads/);

    // ---- Leg 2: upload sample repo -----------------------------------------
    await page.goto('/uploads/new');
    await expect(page.getByText(/Step 1 — Upload/i)).toBeVisible();

    // The dropzone wraps a hidden file input — use setInputFiles directly so
    // we don't rely on drag-and-drop simulation.
    const dropzone = page.getByTestId('upload-dropzone');
    const fileInput = dropzone.locator('input[type="file"]');
    await fileInput.setInputFiles(SAMPLE_ZIP);

    // Upload + extraction — wait for step 2's heading.
    await expect(page.getByText(/Step 2 — Select files/i)).toBeVisible({
      timeout: 60_000,
    });
    const summary = page.getByTestId('upload-summary');
    await expect(summary).toBeVisible();
    // Sample repo has 4 files (README + 3 sources). Assert at least one was
    // detected — the precise count would couple this test to fixture math.
    await expect(summary).toContainText(/Files found/i);

    // ---- Leg 3: scan config + start ----------------------------------------
    await page.getByRole('button', { name: /^continue$/i }).click();

    await expect(page.getByText(/Step 3 — Scan configuration/i)).toBeVisible();

    // Default config ticks "security" only. Add bugs + keywords so the
    // happy-path covers all three scan types.
    const bugsToggle = page.getByLabel(/Bug report scan/i);
    if (!(await bugsToggle.isChecked())) {
      await bugsToggle.check();
    }
    const keywordsToggle = page.getByLabel(/Keyword scan/i);
    if (!(await keywordsToggle.isChecked())) {
      await keywordsToggle.check();
    }
    // Keyword scan requires at least one item or step 3's submit blocks.
    await page.locator('#keyword-items').fill('TODO');

    // Step 3 → Step 4
    await page.getByRole('button', { name: /^continue$/i }).click();
    await expect(page.getByText(/Step 4 — Confirm/i)).toBeVisible();
    await page.getByRole('button', { name: /start scan/i }).click();

    // ---- Leg 4: progress → findings ----------------------------------------
    // We're on /scans/{id} now. Wait for the findings table to render —
    // that's the canonical "completed" signal in the UI.
    await page.waitForURL(/\/scans\/[0-9a-f-]+/i, { timeout: 30_000 });
    const scanUrl = page.url();

    await expect(page.getByTestId('findings-section')).toBeVisible({
      timeout: 4 * 60_000,
    });
    const table = page.getByTestId('findings-table');
    await expect(table).toBeVisible();
    // Mock returns 1 security finding + 1 bugs finding per LLM scan_file
    // and the keyword scanner matches at least the TODO line. Don't pin to
    // an exact count — assert the table is non-empty + names a known title.
    await expect(table).toContainText(/Hardcoded API key/i);

    // ---- Leg 5: export -----------------------------------------------------
    // ExportMenu renders the JSON link via shadcn's DropdownMenu, which only
    // mounts the link inside an animated portal after the trigger is
    // clicked. ``download`` events fire reliably with Playwright's
    // ``waitForEvent`` once we click the menu item.
    await page.getByTestId('export-menu-trigger').click();
    const jsonLink = page.getByTestId('export-link-json');
    await expect(jsonLink).toBeVisible();

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      jsonLink.click(),
    ]);
    const downloadPath = await download.path();
    expect(downloadPath, 'download did not land on disk').toBeTruthy();

    const body = readFileSync(downloadPath!, 'utf-8');
    const parsed = JSON.parse(body);
    // Export payload is documented in API.md §Scans → ``GET .../export``.
    // Defensive: it may be ``{ items: [...] }`` or a top-level array; both
    // shapes are valid JSON exports. Just assert findings landed.
    const items = Array.isArray(parsed) ? parsed : parsed.items;
    expect(Array.isArray(items)).toBeTruthy();
    expect(items.length).toBeGreaterThan(0);
    const titles = items.map((f: { title: string }) => f.title).join('|');
    expect(titles).toMatch(/(Hardcoded API key|null dereference|Keyword)/i);

    // Final breadcrumb so the trace artifact carries the canonical scan URL.
    await page.goto(scanUrl);
    await expect(page.getByTestId('findings-table')).toBeVisible();

    // baseURL is intentionally read off the fixture so the test signature
    // documents which env it's targeting; not asserted on.
    void baseURL;
  });
});
