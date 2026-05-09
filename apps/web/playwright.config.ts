import { defineConfig, devices } from '@playwright/test';

const isCI = !!process.env.CI;

// Realistic-pacing slowMo. The user explicitly asked the journey not to feel
// robotic — 300ms between every action lets a viewer follow along while
// still keeping the full happy-path under the 10-minute CI budget.
const SLOW_MO_MS = Number(process.env.E2E_SLOW_MO_MS ?? 300);

const WEB_BASE_URL = process.env.E2E_WEB_BASE_URL ?? 'http://localhost:3000';

export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: isCI,
  workers: 1,
  // The full happy-path bounces through long-poll loops (upload extraction,
  // scan progress) so individual assertions need a generous-but-bounded
  // timeout. 90s per assertion + 6 minutes per test keeps the suite well
  // under the 10-minute AC even on a cold runner.
  expect: { timeout: 90_000 },
  timeout: 6 * 60_000,
  reporter: isCI
    ? [['line'], ['html', { open: 'never', outputFolder: 'playwright-report' }]]
    : [['list']],
  globalSetup: require.resolve('./e2e/global-setup'),
  use: {
    baseURL: WEB_BASE_URL,
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
    // Always emit a trace for the failing run so CI artifacts have
    // everything needed to diagnose. Local runs default to off-on-success
    // (cheap) but capture-on-retry (informative).
    trace: isCI ? 'on-first-retry' : 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: isCI ? 'retain-on-failure' : 'off',
    launchOptions: {
      slowMo: SLOW_MO_MS,
    },
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Headless in CI; headed locally so the user can watch the journey.
        // ``PWDEBUG`` (set by ``--debug``) takes precedence regardless.
        headless: isCI,
      },
    },
  ],
});
