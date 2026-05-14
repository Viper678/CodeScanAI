'use client';

import { useCallback, useEffect, useMemo, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { CheckSquare, Eye, RotateCcw, Search, Square, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

import { TreeNodeRow } from './tree-node';
import { useFileTree } from './use-file-tree';
import type { Selection, TreeFile, TreeNode } from './types';

export type FileTreeProps = {
  files: ReadonlyArray<TreeFile>;
  selection: Selection;
  onSelectionChange: (next: Set<string>) => void;
  /** Optional className applied to the outer container. */
  className?: string;
  /** Pixel height of the virtualized scroll viewport. Default 480. */
  height?: number;
};

const ROW_HEIGHT = 28;

/**
 * Virtualized directory tree with tri-state checkboxes, search, toolbar, and
 * keyboard navigation. See docs/UI_DESIGN.md §`<DirectoryTree />` and
 * docs/FILE_HANDLING.md §"Tree presentation contract" for the spec.
 */
export function FileTree({
  files,
  selection,
  onSelectionChange,
  className,
  height = 480,
}: Readonly<FileTreeProps>) {
  const tree = useFileTree({ files, selection, onSelectionChange });
  const {
    rows,
    query,
    setQuery,
    showOnlySelected,
    toggleShowOnlySelected,
    focusedId,
    setFocusedId,
    getState,
    toggle,
    toggleExpand,
    expand,
    collapse,
    selectAll,
    deselectAll,
    resetToDefaults,
  } = tree;

  const scrollRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  // Map id → row index for O(1) keyboard lookups.
  const indexById = useMemo(() => {
    const m = new Map<string, number>();
    rows.forEach((r, i) => m.set(r.node.id, i));
    return m;
  }, [rows]);

  const focusedIndex = focusedId ? (indexById.get(focusedId) ?? -1) : -1;

  const moveFocus = useCallback(
    (next: number) => {
      const clamped = Math.max(0, Math.min(rows.length - 1, next));
      const target = rows[clamped];
      if (!target) return;
      setFocusedId(target.node.id);
      virtualizer.scrollToIndex(clamped, { align: 'auto' });
    },
    [rows, setFocusedId, virtualizer],
  );

  // Initialize focus to the first row once rows are available.
  useEffect(() => {
    if (focusedId === null && rows.length > 0) {
      setFocusedId(rows[0]!.node.id);
    }
  }, [focusedId, rows, setFocusedId]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      // Let users type in the search box without us swallowing keys.
      const target = event.target as HTMLElement;
      if (
        target.tagName === 'INPUT' &&
        target.getAttribute('type') !== 'checkbox'
      ) {
        return;
      }

      // ⌘/Ctrl + A → select all visible.
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'a') {
        event.preventDefault();
        selectAll();
        return;
      }

      if (focusedIndex < 0) return;
      const current = rows[focusedIndex];
      if (!current) return;

      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault();
          moveFocus(focusedIndex + 1);
          break;
        case 'ArrowUp':
          event.preventDefault();
          moveFocus(focusedIndex - 1);
          break;
        case 'ArrowRight': {
          event.preventDefault();
          if (current.isExpandable && !current.isExpanded) {
            expand(current.node.path);
          } else if (current.isExpandable && current.isExpanded) {
            // Move to first child.
            moveFocus(focusedIndex + 1);
          }
          break;
        }
        case 'ArrowLeft': {
          event.preventDefault();
          if (current.isExpandable && current.isExpanded) {
            collapse(current.node.path);
          } else {
            // Move to parent: scan upward for the row at depth = current.depth - 1.
            for (let i = focusedIndex - 1; i >= 0; i -= 1) {
              const candidate = rows[i];
              if (candidate && candidate.depth < current.depth) {
                moveFocus(i);
                break;
              }
            }
          }
          break;
        }
        case ' ':
        case 'Enter':
          event.preventDefault();
          toggle(current.node);
          break;
        default:
          break;
      }
    },
    [collapse, expand, focusedIndex, moveFocus, rows, selectAll, toggle],
  );

  const handleRowToggleExpand = useCallback(
    (node: TreeNode) => {
      toggleExpand(node.path);
    },
    [toggleExpand],
  );

  const handleRowFocus = useCallback(
    (node: TreeNode) => {
      setFocusedId(node.id);
    },
    [setFocusedId],
  );

  const handleSearchKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'Escape') {
        setQuery('');
      }
    },
    [setQuery],
  );

  const items = virtualizer.getVirtualItems();

  return (
    <div
      className={cn(
        'flex flex-col overflow-hidden rounded-lg border border-border bg-card',
        className,
      )}
    >
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder="Filter by path…"
            aria-label="Filter files"
            className="h-7 px-7 text-xs"
          />
          {query && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setQuery('')}
              className="absolute right-1.5 top-1/2 flex size-4 -translate-y-1/2 items-center justify-center rounded-sm text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="size-3" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 border-b border-border px-3 py-2">
        <Button size="xs" variant="ghost" onClick={selectAll}>
          <CheckSquare className="size-3" aria-hidden="true" /> Select all
        </Button>
        <Button size="xs" variant="ghost" onClick={deselectAll}>
          <Square className="size-3" aria-hidden="true" /> Deselect all
        </Button>
        <Button size="xs" variant="ghost" onClick={resetToDefaults}>
          <RotateCcw className="size-3" aria-hidden="true" /> Reset to defaults
        </Button>
        <Button
          size="xs"
          variant={showOnlySelected ? 'secondary' : 'ghost'}
          onClick={toggleShowOnlySelected}
          aria-pressed={showOnlySelected}
        >
          <Eye className="size-3" aria-hidden="true" /> Show only selected
        </Button>
        <span className="ml-auto text-xs text-muted-foreground">
          {selection.size} selected · {rows.length} visible
        </span>
      </div>

      <div
        ref={scrollRef}
        role="tree"
        aria-label="Upload file tree"
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className="relative overflow-auto outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        style={{ height }}
      >
        {rows.length === 0 ? (
          <div className="flex h-full items-center justify-center px-4 py-8 text-center text-xs text-muted-foreground">
            {query
              ? 'No files match the current filter.'
              : showOnlySelected
                ? 'No files selected yet.'
                : 'This upload contains no files.'}
          </div>
        ) : (
          <div
            style={{
              height: `${virtualizer.getTotalSize()}px`,
              position: 'relative',
              width: '100%',
            }}
          >
            {items.map((virtualRow) => {
              const row = rows[virtualRow.index];
              if (!row) return null;
              return (
                <div
                  key={row.node.id}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: `${virtualRow.size}px`,
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                >
                  <TreeNodeRow
                    node={row.node}
                    depth={row.depth}
                    isExpanded={row.isExpanded}
                    isExpandable={row.isExpandable}
                    state={getState(row.node)}
                    isFocused={row.node.id === focusedId}
                    onToggleSelect={toggle}
                    onToggleExpand={handleRowToggleExpand}
                    onFocus={handleRowFocus}
                  />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
