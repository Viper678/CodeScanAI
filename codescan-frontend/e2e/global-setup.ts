import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * Pre-flight: build the deterministic sample zip via Python (CI + local
 * have python3 available). The literal AIzaSy-shaped credential lives only
 * inside the generated zip — never in source — so gitleaks doesn't trip.
 *
 * The script is idempotent: a stale zip is overwritten in place. Skipping
 * when present would race with intentional fixture rebuilds during dev.
 */
export default async function globalSetup(): Promise<void> {
  const fixturesDir = resolve(__dirname, 'fixtures');
  const builder = resolve(fixturesDir, 'build_sample_zip.py');
  if (!existsSync(builder)) {
    throw new Error(`Sample-zip builder missing at ${builder}`);
  }
  // ``python3`` is guaranteed in the CI matrix (actions/setup-python) and
  // the dev README assumes a working local Python. Inheriting stderr
  // surfaces the "wrote ..." breadcrumb in the test log.
  execFileSync('python3', [builder], {
    stdio: ['ignore', 'inherit', 'inherit'],
  });
}
