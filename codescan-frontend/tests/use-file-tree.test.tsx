import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useFileTree } from '@/components/file-tree/use-file-tree';
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

const FILES: TreeFile[] = [
  file('a', 'src/auth.py'),
  file('b', 'src/users.py'),
  file('c', 'tests/test_auth.py'),
  file('lock', 'pnpm-lock.yaml', {
    is_excluded_by_default: true,
    excluded_reason: 'lockfile',
    language: null,
  }),
];

function setup(initialSelection?: Set<string>) {
  let selection: Set<string> = initialSelection ?? new Set();
  const onChange = (next: Set<string>) => {
    selection = next;
    rerender();
  };
  const { result, rerender: doRerender } = renderHook(() =>
    useFileTree({
      files: FILES,
      selection,
      onSelectionChange: onChange,
    }),
  );
  function rerender() {
    doRerender();
  }
  return {
    get result() {
      return result;
    },
    get selection() {
      return selection;
    },
  };
}

describe('useFileTree reducer', () => {
  it('starts with default expansion (top-level dirs expanded)', () => {
    const ctx = setup();
    const paths = ctx.result.current.rows.map((r) => r.node.path);
    expect(paths).toContain('src');
    expect(paths).toContain('src/auth.py');
    expect(paths).toContain('tests');
  });

  it('toggleExpand collapses a directory', () => {
    const ctx = setup();
    act(() => {
      ctx.result.current.toggleExpand('src');
    });
    const paths = ctx.result.current.rows.map((r) => r.node.path);
    expect(paths).toContain('src');
    expect(paths).not.toContain('src/auth.py');
  });

  it('search query auto-expands ancestors of matches', () => {
    const ctx = setup();
    // Collapse first.
    act(() => {
      ctx.result.current.toggleExpand('src');
    });
    expect(ctx.result.current.rows.map((r) => r.node.path)).not.toContain(
      'src/auth.py',
    );
    act(() => {
      ctx.result.current.setQuery('auth');
    });
    const paths = ctx.result.current.rows.map((r) => r.node.path);
    expect(paths).toContain('src');
    expect(paths).toContain('src/auth.py');
    expect(paths).toContain('tests');
    expect(paths).toContain('tests/test_auth.py');
  });

  it('selectAll picks every non-excluded leaf in the visible tree', () => {
    const ctx = setup();
    act(() => {
      ctx.result.current.selectAll();
    });
    expect(ctx.selection).toEqual(new Set(['a', 'b', 'c']));
    expect(ctx.selection.has('lock')).toBe(false);
  });

  it('deselectAll clears the selection', () => {
    const ctx = setup(new Set(['a', 'b']));
    act(() => {
      ctx.result.current.deselectAll();
    });
    expect(ctx.selection).toEqual(new Set());
  });

  it('resetToDefaults restores the default selection and resets filters', () => {
    const ctx = setup(new Set(['lock']));
    act(() => {
      ctx.result.current.setQuery('auth');
      ctx.result.current.setShowOnlySelected(true);
    });
    act(() => {
      ctx.result.current.resetToDefaults();
    });
    expect(ctx.selection).toEqual(new Set(['a', 'b', 'c']));
    expect(ctx.result.current.query).toBe('');
    expect(ctx.result.current.showOnlySelected).toBe(false);
  });

  it('toggleShowOnlySelected restricts visible rows to ancestors of selected leaves', () => {
    const ctx = setup(new Set(['c']));
    act(() => {
      ctx.result.current.toggleShowOnlySelected();
    });
    const paths = ctx.result.current.rows.map((r) => r.node.path);
    expect(paths).toContain('tests');
    expect(paths).toContain('tests/test_auth.py');
    expect(paths).not.toContain('src');
    expect(paths).not.toContain('pnpm-lock.yaml');
  });

  it('focus falls back to the first visible row when the focused row disappears', () => {
    const ctx = setup();
    act(() => {
      ctx.result.current.setFocusedId('a-nonexistent-id');
    });
    // The hook normalises invalid focus targets to the first row on next render.
    const firstId = ctx.result.current.rows[0]!.node.id;
    expect(ctx.result.current.focusedId).toBe(firstId);
  });
});
