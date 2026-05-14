import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeAll } from 'vitest';

import { FileTree } from '@/components/file-tree/file-tree';
import type { TreeFile } from '@/components/file-tree/types';

// jsdom doesn't lay out scroll containers, which trips up react-virtual's
// measurement loop. Mock its hook to return all rows synchronously, which is
// what we want for keyboard tests anyway.
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getVirtualItems: () =>
      Array.from({ length: count }, (_, i) => ({
        index: i,
        key: i,
        size: 28,
        start: i * 28,
        end: (i + 1) * 28,
        lane: 0,
      })),
    getTotalSize: () => count * 28,
    scrollToIndex: vi.fn(),
  }),
}));

beforeAll(() => {
  // Required by some shadcn primitives in jsdom.
  if (!('PointerEvent' in window)) {
    // reason: jsdom omits PointerEvent which @base-ui/react's button uses.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).PointerEvent = MouseEvent;
  }
});

const FILES: TreeFile[] = [
  {
    id: 'a',
    path: 'src/auth.py',
    parent_path: 'src',
    name: 'auth.py',
    size_bytes: 100,
    language: 'python',
    is_binary: false,
    is_excluded_by_default: false,
    excluded_reason: null,
  },
  {
    id: 'b',
    path: 'src/users.py',
    parent_path: 'src',
    name: 'users.py',
    size_bytes: 200,
    language: 'python',
    is_binary: false,
    is_excluded_by_default: false,
    excluded_reason: null,
  },
  {
    id: 'c',
    path: 'tests/test_auth.py',
    parent_path: 'tests',
    name: 'test_auth.py',
    size_bytes: 50,
    language: 'python',
    is_binary: false,
    is_excluded_by_default: false,
    excluded_reason: null,
  },
  {
    id: 'lock',
    path: 'pnpm-lock.yaml',
    parent_path: '',
    name: 'pnpm-lock.yaml',
    size_bytes: 9999,
    language: null,
    is_binary: false,
    is_excluded_by_default: true,
    excluded_reason: 'lockfile',
  },
];

function ControlledFileTree() {
  const [selection, setSelection] = React.useState<Set<string>>(new Set());
  return (
    <FileTree
      files={FILES}
      selection={selection}
      onSelectionChange={setSelection}
      height={400}
    />
  );
}

describe('FileTree keyboard interaction', () => {
  it('renders rows for the visible tree', () => {
    render(<ControlledFileTree />);
    expect(screen.getByRole('tree')).toBeInTheDocument();
    // Top-level dirs are auto-expanded; their children show.
    expect(screen.getAllByRole('treeitem').length).toBeGreaterThan(2);
  });

  it('marks excluded rows with their reason badge', () => {
    render(<ControlledFileTree />);
    expect(screen.getByText('lockfile')).toBeInTheDocument();
  });

  it('moves focus down with ArrowDown and toggles selection with Space', async () => {
    const user = userEvent.setup();
    render(<ControlledFileTree />);
    const tree = screen.getByRole('tree');
    tree.focus();

    // Initial focus should be on the first row.
    const before = tree.querySelector('[aria-selected="true"]');
    expect(before).not.toBeNull();

    await user.keyboard('{ArrowDown}{ArrowDown}');
    const after = tree.querySelector('[aria-selected="true"]');
    expect(after).not.toBeNull();
    expect(after).not.toBe(before);

    // Toggle selection on the focused row via Space — count selected reflected
    // in the toolbar status text "N selected".
    await user.keyboard(' ');
    expect(screen.getByText(/\d+ selected/i)).toBeInTheDocument();
  });

  it('Cmd/Ctrl+A selects all non-excluded visible files', async () => {
    const user = userEvent.setup();
    render(<ControlledFileTree />);
    screen.getByRole('tree').focus();
    await user.keyboard('{Control>}a{/Control}');
    // 3 non-excluded files in the fixture.
    expect(screen.getByText(/3 selected/)).toBeInTheDocument();
  });

  it('Select-all toolbar button respects the exclusion bypass', async () => {
    const user = userEvent.setup();
    render(<ControlledFileTree />);
    await user.click(screen.getByRole('button', { name: /^select all$/i }));
    expect(screen.getByText(/3 selected/)).toBeInTheDocument();
  });
});
