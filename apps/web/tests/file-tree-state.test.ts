import { describe, expect, it } from 'vitest';

import {
  allDirPaths,
  ancestorPaths,
  applyDefaultSelection,
  buildTree,
  collectLeaves,
  defaultExpansion,
  filterToSelected,
  filterTree,
  flattenVisible,
  getDirState,
  toggleNode,
} from '@/components/file-tree/tree-state';
import type { TreeFile } from '@/components/file-tree/types';

function file(
  id: string,
  path: string,
  overrides: Partial<TreeFile> = {},
): TreeFile {
  const segments = path.split('/');
  const name = segments[segments.length - 1] ?? path;
  const parent_path = segments.slice(0, -1).join('/');
  return {
    id,
    path,
    parent_path,
    name,
    size_bytes: 100,
    language: 'python',
    is_binary: false,
    is_excluded_by_default: false,
    excluded_reason: null,
    ...overrides,
  };
}

const SAMPLE: TreeFile[] = [
  file('a', 'src/api/auth.py'),
  file('b', 'src/api/users.py'),
  file('c', 'src/web/index.tsx', { language: 'typescript' }),
  file('d', 'tests/test_auth.py'),
  file('e', 'README.md', { language: 'markdown' }),
  // Surfaced excluded vendor dir (matches API.md example).
  file('vendor-dir', 'node_modules', {
    parent_path: '',
    size_bytes: 0,
    language: null,
    is_excluded_by_default: true,
    excluded_reason: 'vendor_dir',
  }),
  file('v1', 'node_modules/foo/index.js', {
    is_excluded_by_default: true,
    excluded_reason: 'vendor_dir',
    language: 'javascript',
  }),
];

describe('buildTree', () => {
  it('groups by parent path and infers missing directories', () => {
    const root = buildTree(SAMPLE);
    // Synthetic root has no name and no fileId.
    expect(root.kind).toBe('dir');
    expect(root.path).toBe('');

    const topNames = root.children!.map((n) => n.name).sort();
    expect(topNames).toEqual(['README.md', 'node_modules', 'src', 'tests']);

    const src = root.children!.find((n) => n.name === 'src')!;
    expect(src.kind).toBe('dir');
    expect(src.children!.map((c) => c.name).sort()).toEqual(['api', 'web']);

    const api = src.children!.find((n) => n.name === 'api')!;
    expect(api.children!.map((c) => c.name).sort()).toEqual([
      'auth.py',
      'users.py',
    ]);
  });

  it('sorts directories before files within each level', () => {
    const root = buildTree(SAMPLE);
    const kinds = root.children!.map((c) => c.kind);
    // Dirs first then file.
    expect(kinds).toEqual(['dir', 'dir', 'dir', 'file']);
  });

  it('recognizes a surfaced excluded directory entry as a directory', () => {
    const root = buildTree(SAMPLE);
    const node_modules = root.children!.find((n) => n.name === 'node_modules')!;
    expect(node_modules.kind).toBe('dir');
    expect(node_modules.is_excluded_by_default).toBe(true);
    expect(node_modules.excluded_reason).toBe('vendor_dir');
    // And its children are still attached so the user can drill in.
    expect(node_modules.children!.length).toBeGreaterThan(0);
  });

  it('is defensive about input order', () => {
    const reversed = [...SAMPLE].reverse();
    const a = buildTree(SAMPLE);
    const b = buildTree(reversed);
    const aLeaves = collectLeaves(a)
      .map((l) => l.path)
      .sort();
    const bLeaves = collectLeaves(b)
      .map((l) => l.path)
      .sort();
    expect(aLeaves).toEqual(bLeaves);
  });
});

describe('getDirState', () => {
  const root = buildTree(SAMPLE);
  const src = root.children!.find((n) => n.name === 'src')!;

  it('returns unchecked when no leaves are selected', () => {
    expect(getDirState(src, new Set())).toBe('unchecked');
  });

  it('returns checked when every leaf is selected', () => {
    const ids = collectLeaves(src).map((l) => l.fileId!);
    expect(getDirState(src, new Set(ids))).toBe('checked');
  });

  it('returns indeterminate when some leaves are selected', () => {
    expect(getDirState(src, new Set(['a']))).toBe('indeterminate');
  });

  it('reports file leaves directly', () => {
    const readme = root.children!.find((n) => n.name === 'README.md')!;
    expect(getDirState(readme, new Set())).toBe('unchecked');
    expect(getDirState(readme, new Set(['e']))).toBe('checked');
  });
});

describe('toggleNode', () => {
  const root = buildTree(SAMPLE);
  const src = root.children!.find((n) => n.name === 'src')!;
  const node_modules = root.children!.find((n) => n.name === 'node_modules')!;

  it('selects all non-excluded descendants from unchecked', () => {
    const result = toggleNode(src, new Set());
    // src has 3 non-excluded leaves: a, b, c.
    expect(result).toEqual(new Set(['a', 'b', 'c']));
  });

  it('selects all non-excluded descendants from indeterminate (per spec)', () => {
    // Start with one of src's leaves selected.
    const result = toggleNode(src, new Set(['a']));
    expect(result).toEqual(new Set(['a', 'b', 'c']));
  });

  it('does not select excluded leaves on toggle-on', () => {
    const result = toggleNode(node_modules, new Set());
    // The only leaf under node_modules is `v1` and it is excluded.
    expect(result.has('v1')).toBe(false);
    expect(result.size).toBe(0);
  });

  it('deselects all descendants when checked, including any user-revealed excluded ones', () => {
    // User had selected the excluded leaf manually plus the regulars.
    const start = new Set(['a', 'b', 'c', 'v1']);
    // src is fully checked over its non-excluded leaves; toggle from checked.
    const allSrcLeaves = collectLeaves(src).map((l) => l.fileId!);
    const checkedSet = new Set(allSrcLeaves);
    const result = toggleNode(src, checkedSet);
    expect(result.size).toBe(0);
    // Independent: toggling node_modules (which is "checked" against just v1)
    // wipes v1.
    const r2 = toggleNode(node_modules, new Set(['v1']));
    expect(r2.has('v1')).toBe(false);
    void start;
  });

  it('toggles a single file regardless of exclusion (user opt-in)', () => {
    const v1 = collectLeaves(node_modules).find((l) => l.fileId === 'v1')!;
    const r = toggleNode(v1, new Set());
    expect(r.has('v1')).toBe(true);
    const r2 = toggleNode(v1, new Set(['v1']));
    expect(r2.has('v1')).toBe(false);
  });
});

describe('applyDefaultSelection', () => {
  it('returns every non-excluded leaf', () => {
    const root = buildTree(SAMPLE);
    const def = applyDefaultSelection(root);
    expect(def).toEqual(new Set(['a', 'b', 'c', 'd', 'e']));
    expect(def.has('v1')).toBe(false);
  });
});

describe('filterTree', () => {
  const root = buildTree(SAMPLE);

  it('returns the original tree for an empty query', () => {
    const r = filterTree(root, '');
    expect(r.tree).toBe(root);
    expect(r.expand.size).toBe(0);
  });

  it('keeps only ancestors of matching leaves and lists them in expand', () => {
    const r = filterTree(root, 'auth');
    // Should include src, src/api (ancestors of auth.py + test_auth.py), tests.
    expect(r.expand.has('src')).toBe(true);
    expect(r.expand.has('src/api')).toBe(true);
    expect(r.expand.has('tests')).toBe(true);
    // Does not expand siblings without matches.
    expect(r.expand.has('src/web')).toBe(false);
    // Tree only contains matching subtrees.
    const topNames = r.tree.children!.map((c) => c.name).sort();
    expect(topNames).toEqual(['src', 'tests']);
  });

  it('is case-insensitive', () => {
    const r = filterTree(root, 'README');
    const lower = filterTree(root, 'readme');
    expect(r.tree.children!.map((c) => c.name)).toEqual(
      lower.tree.children!.map((c) => c.name),
    );
  });
});

describe('filterToSelected', () => {
  it('keeps only selected leaves and their ancestors', () => {
    const root = buildTree(SAMPLE);
    const selection = new Set(['a', 'd']);
    const r = filterToSelected(root, selection);
    const topNames = r.tree.children!.map((c) => c.name).sort();
    expect(topNames).toEqual(['src', 'tests']);
    expect(r.expand.has('src')).toBe(true);
    expect(r.expand.has('src/api')).toBe(true);
  });
});

describe('flattenVisible + defaultExpansion', () => {
  it('emits only top-level items by default', () => {
    const root = buildTree(SAMPLE);
    const expanded = defaultExpansion(root);
    const rows = flattenVisible(root, expanded);
    // We expand top-level dirs by default but not deeper, so we get the
    // top-level rows + their immediate children.
    const paths = rows.map((r) => r.node.path);
    expect(paths).toContain('src');
    expect(paths).toContain('src/api');
    // src/api is collapsed by default, so its children must NOT appear.
    expect(paths).not.toContain('src/api/auth.py');
    expect(paths).toContain('README.md');
  });

  it('respects expansion changes', () => {
    const root = buildTree(SAMPLE);
    const expanded = new Set(['src', 'src/api']);
    const rows = flattenVisible(root, expanded);
    const paths = rows.map((r) => r.node.path);
    expect(paths).toContain('src/api/auth.py');
    expect(paths).toContain('src/api/users.py');
  });
});

describe('ancestorPaths', () => {
  it('returns all parent paths excluding the leaf itself and root', () => {
    expect(ancestorPaths('a/b/c/d.py')).toEqual(['a', 'a/b', 'a/b/c']);
    expect(ancestorPaths('top.py')).toEqual([]);
    expect(ancestorPaths('')).toEqual([]);
  });
});

describe('allDirPaths', () => {
  it('lists every directory path under the root', () => {
    const root = buildTree(SAMPLE);
    const dirs = allDirPaths(root).sort();
    expect(dirs).toContain('src');
    expect(dirs).toContain('src/api');
    expect(dirs).toContain('src/web');
    expect(dirs).toContain('node_modules');
    expect(dirs).not.toContain('');
  });
});
