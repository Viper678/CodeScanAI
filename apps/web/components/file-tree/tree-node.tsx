'use client';

import { memo, useCallback, useEffect, useRef } from 'react';
import {
  ChevronDown,
  ChevronRight,
  File,
  FileCode2,
  Folder,
  FolderOpen,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

import type { CheckState, ExcludedReason, TreeNode } from './types';

export type TreeNodeRowProps = {
  node: TreeNode;
  depth: number;
  isExpanded: boolean;
  isExpandable: boolean;
  state: CheckState;
  isFocused: boolean;
  onToggleSelect: (node: TreeNode) => void;
  onToggleExpand: (node: TreeNode) => void;
  onFocus: (node: TreeNode) => void;
};

const REASON_LABEL: Record<ExcludedReason, string> = {
  oversize: 'oversize',
  binary: 'binary',
  vendor_dir: 'vendor',
  vcs_dir: 'vcs',
  ide_dir: 'ide',
  lockfile: 'lockfile',
  build_artifact: 'build',
  image: 'image',
  font: 'font',
  media: 'media',
  archive: 'archive',
  dotfile: 'dotfile',
  unknown_ext: 'unknown ext',
};

function formatSize(bytes: number | undefined): string | null {
  if (bytes === undefined) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * One row in the virtualized tree. Memoized: virtualization re-renders the
 * list aggressively, but a single row only changes if its props do.
 */
function TreeNodeRowComponent({
  node,
  depth,
  isExpanded,
  isExpandable,
  state,
  isFocused,
  onToggleSelect,
  onToggleExpand,
  onFocus,
}: Readonly<TreeNodeRowProps>) {
  const checkboxRef = useRef<HTMLInputElement>(null);

  // The native HTML checkbox doesn't expose `indeterminate` declaratively.
  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = state === 'indeterminate';
    }
  }, [state]);

  const handleCheckbox = useCallback(
    (event: React.MouseEvent<HTMLInputElement>) => {
      event.stopPropagation();
      onToggleSelect(node);
    },
    [node, onToggleSelect],
  );

  const handleChevron = useCallback(
    (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      onToggleExpand(node);
    },
    [node, onToggleExpand],
  );

  const handleRowClick = useCallback(() => {
    onFocus(node);
  }, [node, onFocus]);

  const muted = node.is_excluded_by_default;
  const Icon =
    node.kind === 'dir'
      ? isExpanded
        ? FolderOpen
        : Folder
      : node.language
        ? FileCode2
        : File;
  const size = formatSize(node.size_bytes);
  const reason = node.excluded_reason;

  return (
    <div
      role="treeitem"
      data-id={node.id}
      data-kind={node.kind}
      aria-level={depth + 1}
      aria-expanded={isExpandable ? isExpanded : undefined}
      aria-selected={isFocused}
      tabIndex={isFocused ? 0 : -1}
      onClick={handleRowClick}
      className={cn(
        'flex h-7 cursor-pointer select-none items-center gap-1.5 rounded-sm px-1 text-sm',
        isFocused && 'bg-accent text-accent-foreground',
        !isFocused && 'hover:bg-muted/60',
        muted && 'opacity-60',
      )}
      style={{ paddingLeft: `${depth * 16 + 4}px` }}
    >
      {isExpandable ? (
        <button
          type="button"
          aria-label={isExpanded ? 'Collapse' : 'Expand'}
          tabIndex={-1}
          onClick={handleChevron}
          className="flex size-4 items-center justify-center rounded-sm text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {isExpanded ? (
            <ChevronDown className="size-3.5" aria-hidden="true" />
          ) : (
            <ChevronRight className="size-3.5" aria-hidden="true" />
          )}
        </button>
      ) : (
        <span className="size-4" aria-hidden="true" />
      )}

      <input
        ref={checkboxRef}
        type="checkbox"
        aria-label={`Select ${node.path || node.name}`}
        tabIndex={-1}
        checked={state === 'checked'}
        onClick={handleCheckbox}
        onChange={() => {
          // Mouse handled in onClick above to allow stopPropagation; the
          // change event is also fired when toggled via keyboard space, in
          // which case the parent's onKeyDown already dispatched the toggle.
          // We need the handler to keep React's controlled-input contract.
        }}
        className="size-3.5 cursor-pointer rounded-sm border-input accent-primary"
      />

      <Icon
        className={cn(
          'size-3.5 shrink-0',
          node.kind === 'dir'
            ? 'text-muted-foreground'
            : 'text-muted-foreground',
        )}
        aria-hidden="true"
      />

      <span
        className={cn(
          'truncate font-mono text-[13px]',
          muted && 'line-through decoration-muted-foreground/50',
        )}
        title={node.path || node.name}
      >
        {node.name}
      </span>

      {node.language && (
        <Badge
          variant="outline"
          className="ml-1 h-4 px-1 text-[10px] font-normal"
        >
          {node.language}
        </Badge>
      )}

      {size && node.kind === 'file' && (
        <span className="ml-auto pl-2 text-[11px] text-muted-foreground">
          {size}
        </span>
      )}

      {reason && (
        <Badge
          variant="outline"
          className={cn(
            'h-4 px-1 text-[10px] font-normal text-muted-foreground',
            !size || node.kind !== 'file' ? 'ml-auto' : 'ml-1.5',
          )}
        >
          {REASON_LABEL[reason]}
        </Badge>
      )}
    </div>
  );
}

export const TreeNodeRow = memo(TreeNodeRowComponent);
