import type { ExcludedReason, TreeFile } from '@/components/file-tree/types';

const EXTS = ['ts', 'tsx', 'js', 'py', 'go', 'rs', 'java', 'rb', 'json', 'md'];
const LANGS: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  py: 'python',
  go: 'go',
  rs: 'rust',
  java: 'java',
  rb: 'ruby',
  json: 'json',
  md: 'markdown',
};

/**
 * Generate a deterministic in-memory tree for the demo page perf check. Mixes
 * a couple of "vendor" branches in so the muted/excluded styling is visible.
 */
export function generateFixture(count: number): TreeFile[] {
  const files: TreeFile[] = [];

  // Surface an excluded `node_modules` so the muted dir styling shows up.
  files.push({
    id: 'dir:node_modules',
    path: 'node_modules',
    parent_path: '',
    name: 'node_modules',
    size_bytes: 0,
    language: null,
    is_binary: false,
    is_excluded_by_default: true,
    excluded_reason: 'vendor_dir',
  });

  // ~5% of files live under node_modules and are excluded.
  const vendorCount = Math.floor(count * 0.05);
  const realCount = count - vendorCount;

  // Spread real files across a few top-level dirs and modest depth.
  const topDirs = ['src', 'app', 'lib', 'tests', 'docs'];
  for (let i = 0; i < realCount; i += 1) {
    const top = topDirs[i % topDirs.length]!;
    const sub = `mod${Math.floor(i / 200) % 50}`;
    const leaf = `feature${Math.floor(i / 20) % 200}`;
    const ext = EXTS[i % EXTS.length]!;
    const name = `file_${i}.${ext}`;
    const parent = `${top}/${sub}/${leaf}`;
    const path = `${parent}/${name}`;
    const reason: ExcludedReason | null = i % 137 === 0 ? 'lockfile' : null;
    files.push({
      id: `f-${i}`,
      path,
      parent_path: parent,
      name,
      size_bytes: 100 + ((i * 37) % 5000),
      language: reason ? null : (LANGS[ext] ?? null),
      is_binary: false,
      is_excluded_by_default: reason !== null,
      excluded_reason: reason,
    });
  }

  for (let i = 0; i < vendorCount; i += 1) {
    const sub = `pkg${i % 50}`;
    const path = `node_modules/${sub}/index.js`;
    files.push({
      id: `v-${i}`,
      path,
      parent_path: `node_modules/${sub}`,
      name: 'index.js',
      size_bytes: 2048,
      language: null,
      is_binary: false,
      is_excluded_by_default: true,
      excluded_reason: 'vendor_dir',
    });
  }

  return files;
}
