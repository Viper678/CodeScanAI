/**
 * Pure helpers for the file-tree state machine. No React, no DOM. Everything
 * the component needs to compute (build the tree, tri-state math, toggle
 * cascades, search filter, ancestor expansion) lives here so it can be
 * unit-tested in isolation. See docs/FILE_HANDLING.md §"Tree presentation
 * contract" for the spec these helpers implement.
 */

import type {
  CheckState,
  ExcludedReason,
  Selection,
  TreeFile,
  TreeNode,
} from './types';

/** Sort children: directories before files, then alphabetic by name. */
function sortChildren(children: TreeNode[]): TreeNode[] {
  return [...children].sort((a, b) => {
    if (a.kind !== b.kind) {
      return a.kind === 'dir' ? -1 : 1;
    }
    return a.name.localeCompare(b.name);
  });
}

/** Split a forward-slash path into segments, dropping empties. */
function splitPath(p: string): string[] {
  return p.split('/').filter((s) => s.length > 0);
}

/** Join segments with forward slashes. */
function joinPath(segments: string[]): string {
  return segments.join('/');
}

/** Synthetic id for a directory — distinct from file ids. */
export function dirId(path: string): string {
  return `dir:${path}`;
}

/**
 * Build a tree from the flat list of files returned by the API. Inferred
 * directories (those that exist only as `parent_path` of a child) are created
 * automatically. Directories that have their own row (e.g. surfaced excluded
 * `node_modules`) inherit their `excluded_reason` from that row and the user
 * can still expand them.
 */
export function buildTree(files: ReadonlyArray<TreeFile>): TreeNode {
  // Defensive sort. T2.3 sorts server-side but we don't depend on that.
  const sorted = [...files].sort((a, b) => a.path.localeCompare(b.path));

  // Directory metadata coming from explicit dir rows (excluded_reason mostly).
  const dirMeta = new Map<
    string,
    { excluded: boolean; reason: ExcludedReason | null }
  >();

  // Heuristic: a flat-list entry is a directory row iff another entry's
  // parent_path equals its path, OR it has language=null/is_binary=false but
  // appears as a parent of nothing (rare — mirrors the API.md example for
  // surfaced excluded dirs).
  const allPaths = new Set(sorted.map((f) => f.path));
  const parentPaths = new Set(sorted.map((f) => f.parent_path));

  const leaves: TreeFile[] = [];
  for (const f of sorted) {
    // If this entry's path is some other entry's parent_path, treat it as a
    // directory marker rather than a leaf. This matches the API.md `node_modules`
    // example (which is surfaced as its own row purely so the UI can show the
    // excluded badge).
    if (parentPaths.has(f.path) && f.path !== '') {
      dirMeta.set(f.path, {
        excluded: f.is_excluded_by_default,
        reason: f.excluded_reason,
      });
      continue;
    }
    // A row with no language/binary/size that nobody parents could still be a
    // surfaced excluded dir (e.g. an empty `node_modules` with no children
    // shipped). Heuristic: language === null AND size_bytes === 0 AND name
    // looks like a dir. We err on the side of "treat as leaf" to avoid losing
    // a real empty file; the docs say such surfacing only happens for excluded
    // vendor dirs, which will always have `is_excluded_by_default=true`.
    if (
      f.is_excluded_by_default &&
      f.language === null &&
      f.size_bytes === 0 &&
      !f.name.includes('.')
    ) {
      dirMeta.set(f.path, {
        excluded: true,
        reason: f.excluded_reason,
      });
      continue;
    }
    leaves.push(f);
  }

  // Synthetic root.
  const root: TreeNode = {
    id: dirId(''),
    path: '',
    name: '',
    kind: 'dir',
    children: [],
    is_excluded_by_default: false,
    excluded_reason: null,
  };

  // index of dir path -> node, so we can locate or create on demand.
  const dirIndex = new Map<string, TreeNode>();
  dirIndex.set('', root);

  function ensureDir(path: string): TreeNode {
    const existing = dirIndex.get(path);
    if (existing) return existing;

    const segments = splitPath(path);
    const name = segments[segments.length - 1] ?? '';
    const parentPath = joinPath(segments.slice(0, -1));
    const parent = ensureDir(parentPath);
    const meta = dirMeta.get(path);
    const node: TreeNode = {
      id: dirId(path),
      path,
      name,
      kind: 'dir',
      children: [],
      is_excluded_by_default: meta?.excluded ?? false,
      excluded_reason: meta?.reason ?? null,
    };
    parent.children!.push(node);
    dirIndex.set(path, node);
    return node;
  }

  // Make sure every directory (including those only referenced via leaves'
  // parent_path) exists.
  for (const p of parentPaths) {
    if (p !== '') ensureDir(p);
  }
  // And ensure surfaced excluded dirs are present even if they have no children.
  for (const p of dirMeta.keys()) {
    ensureDir(p);
  }
  // Suppress "unused variable" - allPaths is built for clarity / future debug.
  void allPaths;

  // Now place the leaves.
  for (const f of leaves) {
    const parent = ensureDir(f.parent_path);
    parent.children!.push({
      id: f.id,
      path: f.path,
      name: f.name,
      kind: 'file',
      fileId: f.id,
      size_bytes: f.size_bytes,
      language: f.language,
      is_excluded_by_default: f.is_excluded_by_default,
      excluded_reason: f.excluded_reason,
    });
  }

  // Sort.
  function sortRecursive(node: TreeNode): void {
    if (!node.children) return;
    node.children = sortChildren(node.children);
    for (const c of node.children) sortRecursive(c);
  }
  sortRecursive(root);

  return root;
}

/** Walk a node and yield every leaf descendant. */
export function collectLeaves(node: TreeNode): TreeNode[] {
  if (node.kind === 'file') return [node];
  const out: TreeNode[] = [];
  const stack: TreeNode[] = [node];
  while (stack.length) {
    const n = stack.pop()!;
    if (n.kind === 'file') {
      out.push(n);
    } else if (n.children) {
      for (const c of n.children) stack.push(c);
    }
  }
  return out;
}

/**
 * Tri-state checkbox math per docs/FILE_HANDLING.md.
 *
 * - All leaves selected → 'checked'
 * - Zero leaves selected → 'unchecked'
 * - Mixed → 'indeterminate'
 *
 * For files this is just whether the file is in the selection.
 */
export function getDirState(node: TreeNode, selection: Selection): CheckState {
  if (node.kind === 'file') {
    return selection.has(node.fileId ?? node.id) ? 'checked' : 'unchecked';
  }
  const leaves = collectLeaves(node);
  if (leaves.length === 0) return 'unchecked';
  let selected = 0;
  for (const leaf of leaves) {
    if (selection.has(leaf.fileId ?? leaf.id)) selected += 1;
  }
  if (selected === 0) return 'unchecked';
  if (selected === leaves.length) return 'checked';
  return 'indeterminate';
}

/**
 * Toggle a directory:
 * - unchecked / indeterminate → select all NON-EXCLUDED descendant leaves.
 * - checked → deselect all descendants (including any excluded ones the user
 *   had revealed).
 *
 * Toggle a file:
 * - flip selection membership unconditionally (the user may opt-in to an
 *   excluded file individually).
 */
export function toggleNode(node: TreeNode, selection: Selection): Set<string> {
  const next = new Set(selection);
  if (node.kind === 'file') {
    const id = node.fileId ?? node.id;
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  }

  const state = getDirState(node, selection);
  const leaves = collectLeaves(node);
  if (state === 'checked') {
    for (const leaf of leaves) next.delete(leaf.fileId ?? leaf.id);
  } else {
    for (const leaf of leaves) {
      if (!leaf.is_excluded_by_default) {
        next.add(leaf.fileId ?? leaf.id);
      }
    }
  }
  return next;
}

/** Initial selection = every non-excluded leaf in the tree. */
export function applyDefaultSelection(root: TreeNode): Set<string> {
  const out = new Set<string>();
  for (const leaf of collectLeaves(root)) {
    if (!leaf.is_excluded_by_default) {
      out.add(leaf.fileId ?? leaf.id);
    }
  }
  return out;
}

/** Every non-excluded leaf id in the (possibly filtered) tree. */
export function selectAllVisible(
  visibleLeaves: ReadonlyArray<TreeNode>,
): Set<string> {
  const out = new Set<string>();
  for (const leaf of visibleLeaves) {
    if (!leaf.is_excluded_by_default) {
      out.add(leaf.fileId ?? leaf.id);
    }
  }
  return out;
}

/** All ancestor directory paths of a given node path (excluding root ''). */
export function ancestorPaths(path: string): string[] {
  const segs = splitPath(path);
  const out: string[] = [];
  for (let i = 1; i < segs.length; i += 1) {
    out.push(joinPath(segs.slice(0, i)));
  }
  return out;
}

/**
 * Filter the tree given a search query. The result is a new tree containing
 * only ancestors of files whose path matches `query` (case-insensitive
 * substring). Returns the original root if `query` is empty.
 *
 * Also returns the set of ancestor dir paths that should be auto-expanded so
 * the matches are visible.
 */
export function filterTree(
  root: TreeNode,
  query: string,
): { tree: TreeNode; expand: Set<string> } {
  const trimmed = query.trim();
  if (trimmed.length === 0) {
    return { tree: root, expand: new Set() };
  }
  const needle = trimmed.toLowerCase();
  const expand = new Set<string>();

  function walk(node: TreeNode): TreeNode | null {
    if (node.kind === 'file') {
      return node.path.toLowerCase().includes(needle) ? node : null;
    }
    const kept: TreeNode[] = [];
    for (const child of node.children ?? []) {
      const k = walk(child);
      if (k) kept.push(k);
    }
    if (kept.length === 0) return null;
    if (node.path !== '') expand.add(node.path);
    return { ...node, children: kept };
  }

  const filtered = walk(root) ?? {
    ...root,
    children: [],
  };
  return { tree: filtered, expand };
}

/** Filter to only the ancestor branches leading to selected leaves. */
export function filterToSelected(
  root: TreeNode,
  selection: Selection,
): { tree: TreeNode; expand: Set<string> } {
  const expand = new Set<string>();

  function walk(node: TreeNode): TreeNode | null {
    if (node.kind === 'file') {
      return selection.has(node.fileId ?? node.id) ? node : null;
    }
    const kept: TreeNode[] = [];
    for (const child of node.children ?? []) {
      const k = walk(child);
      if (k) kept.push(k);
    }
    if (kept.length === 0) return null;
    if (node.path !== '') expand.add(node.path);
    return { ...node, children: kept };
  }

  const filtered = walk(root) ?? { ...root, children: [] };
  return { tree: filtered, expand };
}

/** Visible row, after expand/collapse + filter. */
export type VisibleRow = {
  node: TreeNode;
  depth: number;
  isExpanded: boolean;
  /** True for any directory (even with no children) so the chevron is rendered. */
  isExpandable: boolean;
};

/**
 * Flatten the visible tree into a 1D row list given the current expansion set.
 * The synthetic root is never emitted.
 */
export function flattenVisible(
  root: TreeNode,
  expanded: ReadonlySet<string>,
): VisibleRow[] {
  const rows: VisibleRow[] = [];
  function walk(node: TreeNode, depth: number): void {
    if (node !== root) {
      const isExpandable = node.kind === 'dir';
      const isExpanded = isExpandable && expanded.has(node.path);
      rows.push({ node, depth, isExpanded, isExpandable });
      if (isExpandable && !isExpanded) return;
    }
    if (node.children) {
      for (const child of node.children) {
        walk(child, node === root ? 0 : depth + 1);
      }
    }
  }
  walk(root, 0);
  return rows;
}

/** All directory paths in the tree (used for expand-all / collapse-all). */
export function allDirPaths(root: TreeNode): string[] {
  const out: string[] = [];
  const stack: TreeNode[] = [root];
  while (stack.length) {
    const n = stack.pop()!;
    if (n.kind === 'dir') {
      if (n.path !== '') out.push(n.path);
      if (n.children) for (const c of n.children) stack.push(c);
    }
  }
  return out;
}

/**
 * Default expansion: the root's immediate directory children. Keeps the
 * initial render compact while still showing the top of the tree.
 */
export function defaultExpansion(root: TreeNode): Set<string> {
  const out = new Set<string>();
  for (const child of root.children ?? []) {
    if (child.kind === 'dir') out.add(child.path);
  }
  return out;
}

/** Find a node by id by walking the tree. O(n). */
export function findNodeById(root: TreeNode, id: string): TreeNode | null {
  if (root.id === id) return root;
  if (!root.children) return null;
  for (const c of root.children) {
    const m = findNodeById(c, id);
    if (m) return m;
  }
  return null;
}
