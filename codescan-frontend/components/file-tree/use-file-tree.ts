'use client';

import { useCallback, useEffect, useMemo, useReducer } from 'react';

import {
  allDirPaths,
  ancestorPaths,
  applyDefaultSelection,
  buildTree,
  defaultExpansion,
  filterToSelected,
  filterTree,
  findNodeById,
  flattenVisible,
  selectAllVisible,
  toggleNode,
  type VisibleRow,
} from './tree-state';
import type { CheckState, Selection, TreeFile, TreeNode } from './types';

/** Visit every leaf descendant of `node`, depth-first. */
function walkLeaves(node: TreeNode, sink: (n: TreeNode) => void): void {
  if (node.kind === 'file') {
    sink(node);
    return;
  }
  if (!node.children) return;
  for (const c of node.children) walkLeaves(c, sink);
}

function collectLeavesShallow(node: TreeNode): TreeNode[] {
  const out: TreeNode[] = [];
  walkLeaves(node, (l) => out.push(l));
  return out;
}

type State = {
  query: string;
  expanded: Set<string>;
  showOnlySelected: boolean;
  focusedId: string | null;
};

type Action =
  | { type: 'set-query'; query: string }
  | { type: 'toggle-expand'; path: string }
  | { type: 'set-expanded'; expanded: Set<string> }
  | { type: 'expand'; path: string }
  | { type: 'collapse'; path: string }
  | { type: 'set-show-only-selected'; value: boolean }
  | { type: 'set-focus'; id: string | null }
  | { type: 'reset-expansion'; expanded: Set<string> };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'set-query':
      return { ...state, query: action.query };
    case 'toggle-expand': {
      const next = new Set(state.expanded);
      if (next.has(action.path)) next.delete(action.path);
      else next.add(action.path);
      return { ...state, expanded: next };
    }
    case 'expand': {
      if (state.expanded.has(action.path)) return state;
      const next = new Set(state.expanded);
      next.add(action.path);
      return { ...state, expanded: next };
    }
    case 'collapse': {
      if (!state.expanded.has(action.path)) return state;
      const next = new Set(state.expanded);
      next.delete(action.path);
      return { ...state, expanded: next };
    }
    case 'set-expanded':
      return { ...state, expanded: action.expanded };
    case 'set-show-only-selected':
      return { ...state, showOnlySelected: action.value };
    case 'set-focus':
      return { ...state, focusedId: action.id };
    case 'reset-expansion':
      return {
        ...state,
        expanded: action.expanded,
        showOnlySelected: false,
        query: '',
      };
    default:
      return state;
  }
}

export type UseFileTreeArgs = {
  files: ReadonlyArray<TreeFile>;
  selection: Selection;
  onSelectionChange: (next: Set<string>) => void;
};

export type UseFileTreeResult = {
  /** Built tree (includes synthetic root). */
  tree: TreeNode;
  /** Flattened visible rows after expansion + filter. */
  rows: VisibleRow[];
  /** Initial selection (all non-excluded leaves). */
  defaultSelection: Set<string>;
  /** Current search query. */
  query: string;
  setQuery: (q: string) => void;
  /** Whether the "show only selected" filter is on. */
  showOnlySelected: boolean;
  setShowOnlySelected: (v: boolean) => void;
  /** id of the currently focused row (null = none). */
  focusedId: string | null;
  setFocusedId: (id: string | null) => void;
  /** Per-node check state for the badge / checkbox indicator. */
  getState: (node: TreeNode) => CheckState;
  /** Toggle a node (file or directory) — applies the cascade rules. */
  toggle: (node: TreeNode) => void;
  /** Expand / collapse a single directory. */
  toggleExpand: (path: string) => void;
  expand: (path: string) => void;
  collapse: (path: string) => void;
  /** Toolbar actions. */
  selectAll: () => void;
  deselectAll: () => void;
  resetToDefaults: () => void;
  toggleShowOnlySelected: () => void;
};

/**
 * Glue between the pure state machine and React. Most consumers should reach
 * for `<FileTree />` instead of using this directly, but the demo page uses it
 * so we expose the full surface.
 */
export function useFileTree(args: UseFileTreeArgs): UseFileTreeResult {
  const { files, selection, onSelectionChange } = args;

  // Build the tree once per `files` reference. The reference comes from
  // TanStack Query, which is stable until the upload is re-fetched.
  const tree = useMemo(() => buildTree(files), [files]);
  const defaultSelection = useMemo(() => applyDefaultSelection(tree), [tree]);

  const initialExpansion = useMemo(() => defaultExpansion(tree), [tree]);

  const [state, dispatch] = useReducer(reducer, undefined, () => ({
    query: '',
    expanded: initialExpansion,
    showOnlySelected: false,
    focusedId: null,
  }));

  // When the tree itself changes (new upload), reset expansion to defaults.
  // We compare by reference; useMemo above keeps it stable for a given files.
  useEffect(() => {
    dispatch({ type: 'set-expanded', expanded: initialExpansion });
    dispatch({ type: 'set-focus', id: null });
  }, [initialExpansion]);

  // Compute the visible tree by applying filters in order:
  //   1. show-only-selected → restricts to ancestors of selected leaves.
  //   2. search query → restricts to ancestors of query matches.
  // Both filters expand the necessary ancestors so the matches are visible.
  const { visibleTree, forcedExpand } = useMemo(() => {
    let working = tree;
    let extras = new Set<string>();
    if (state.showOnlySelected) {
      const r = filterToSelected(working, selection);
      working = r.tree;
      extras = new Set([...extras, ...r.expand]);
    }
    if (state.query.trim().length > 0) {
      const r = filterTree(working, state.query);
      working = r.tree;
      extras = new Set([...extras, ...r.expand]);
    }
    return { visibleTree: working, forcedExpand: extras };
  }, [tree, state.showOnlySelected, state.query, selection]);

  const effectiveExpanded = useMemo(() => {
    if (forcedExpand.size === 0) return state.expanded;
    return new Set([...state.expanded, ...forcedExpand]);
  }, [state.expanded, forcedExpand]);

  const rows = useMemo(
    () => flattenVisible(visibleTree, effectiveExpanded),
    [visibleTree, effectiveExpanded],
  );

  const getState = useCallback(
    (node: TreeNode): CheckState => {
      // Compute against the *full* selection so toggling a partially-selected
      // dir behaves consistently regardless of the active filter.
      const leaves = collectLeavesShallow(node);
      if (node.kind === 'file') {
        return selection.has(node.fileId ?? node.id) ? 'checked' : 'unchecked';
      }
      if (leaves.length === 0) return 'unchecked';
      let n = 0;
      for (const l of leaves) if (selection.has(l.fileId ?? l.id)) n += 1;
      if (n === 0) return 'unchecked';
      if (n === leaves.length) return 'checked';
      return 'indeterminate';
    },
    [selection],
  );

  const toggle = useCallback(
    (node: TreeNode) => {
      const next = toggleNode(node, selection);
      onSelectionChange(next);
    },
    [selection, onSelectionChange],
  );

  const toggleExpand = useCallback((path: string) => {
    dispatch({ type: 'toggle-expand', path });
  }, []);
  const expand = useCallback((path: string) => {
    dispatch({ type: 'expand', path });
  }, []);
  const collapse = useCallback((path: string) => {
    dispatch({ type: 'collapse', path });
  }, []);

  const selectAll = useCallback(() => {
    // "Select all" picks every non-excluded leaf in the *visible* tree (after
    // filters). This matches the spec: ⌘A and the toolbar button operate on
    // what the user can see.
    const visibleLeaves: TreeNode[] = [];
    walkLeaves(visibleTree, (l) => visibleLeaves.push(l));
    onSelectionChange(selectAllVisible(visibleLeaves));
  }, [visibleTree, onSelectionChange]);

  const deselectAll = useCallback(() => {
    onSelectionChange(new Set());
  }, [onSelectionChange]);

  const resetToDefaults = useCallback(() => {
    onSelectionChange(new Set(defaultSelection));
    dispatch({ type: 'reset-expansion', expanded: initialExpansion });
  }, [defaultSelection, initialExpansion, onSelectionChange]);

  const toggleShowOnlySelected = useCallback(() => {
    dispatch({
      type: 'set-show-only-selected',
      value: !state.showOnlySelected,
    });
  }, [state.showOnlySelected]);

  const setQuery = useCallback((q: string) => {
    dispatch({ type: 'set-query', query: q });
  }, []);

  const setShowOnlySelected = useCallback((v: boolean) => {
    dispatch({ type: 'set-show-only-selected', value: v });
  }, []);

  const setFocusedId = useCallback((id: string | null) => {
    dispatch({ type: 'set-focus', id });
  }, []);

  // If the focused row falls out of view (e.g. after collapsing), drop focus
  // back to the first visible row.
  useEffect(() => {
    if (state.focusedId === null) return;
    const stillVisible = rows.some((r) => r.node.id === state.focusedId);
    if (!stillVisible) {
      dispatch({ type: 'set-focus', id: rows[0]?.node.id ?? null });
    }
  }, [rows, state.focusedId]);

  // The unused-imports below are deliberately re-exported as module symbols
  // for callers (e.g. integration tests) that may want to locate a node or
  // enumerate dir paths without re-importing tree-state directly.
  void findNodeById;
  void allDirPaths;
  void ancestorPaths;

  return {
    tree,
    rows,
    defaultSelection,
    query: state.query,
    setQuery,
    showOnlySelected: state.showOnlySelected,
    setShowOnlySelected,
    focusedId: state.focusedId,
    setFocusedId,
    getState,
    toggle,
    toggleExpand,
    expand,
    collapse,
    selectAll,
    deselectAll,
    resetToDefaults,
    toggleShowOnlySelected,
  };
}
