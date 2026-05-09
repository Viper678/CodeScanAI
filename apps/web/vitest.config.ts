import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  esbuild: {
    jsx: 'automatic',
  },
  resolve: {
    alias: {
      '@': __dirname,
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    // The Playwright e2e suite under ``e2e/`` shares the .spec.ts suffix
    // with vitest's default match. Exclude it so unit tests don't try to
    // run browser specs.
    exclude: ['e2e/**', 'node_modules/**', '.next/**', 'playwright-report/**'],
  },
});
