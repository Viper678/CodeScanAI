/**
 * Types for the file-tree component. Mirrors the over-the-wire shape from
 * `GET /uploads/{id}/tree` documented in docs/API.md §Uploads.
 */

/** A single file row as returned by the API. */
export type TreeFile = {
  id: string;
  path: string;
  parent_path: string;
  name: string;
  size_bytes: number;
  language: string | null;
  is_binary: boolean;
  is_excluded_by_default: boolean;
  excluded_reason: ExcludedReason | null;
};

/** Possible values of `excluded_reason` per docs/FILE_HANDLING.md. */
export type ExcludedReason =
  | 'oversize'
  | 'binary'
  | 'vendor_dir'
  | 'vcs_dir'
  | 'ide_dir'
  | 'lockfile'
  | 'build_artifact'
  | 'image'
  | 'font'
  | 'media'
  | 'archive'
  | 'dotfile'
  | 'unknown_ext';

/**
 * A node in the visual tree. Internal `children` arrays are sorted: directories
 * first, then files, both alphabetic. Each node has a stable `id`:
 * - For leaves it's the API file id.
 * - For directories it's `dir:<path>` (synthetic; matches the directory's path).
 */
export type TreeNode = {
  /** Stable id used for selection / focus tracking. */
  id: string;
  /** Forward-slash path relative to the root. '' for the synthetic root. */
  path: string;
  /** Basename. */
  name: string;
  kind: 'dir' | 'file';
  /** Only meaningful for files. */
  fileId?: string;
  /** Only present for directories. */
  children?: TreeNode[];
  /** Only meaningful for files. */
  size_bytes?: number;
  /** Only meaningful for files. */
  language?: string | null;
  /** True if this row is a default-excluded file/dir. Cascades visually. */
  is_excluded_by_default: boolean;
  /** Present when an excluded reason was provided (file or surfaced dir). */
  excluded_reason: ExcludedReason | null;
};

/** Toggle state for a node's checkbox. */
export type CheckState = 'checked' | 'unchecked' | 'indeterminate';

/** Set of selected file ids (the leaves only — directory state is derived). */
export type Selection = ReadonlySet<string>;
