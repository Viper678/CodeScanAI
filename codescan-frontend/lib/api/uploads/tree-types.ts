/**
 * Wire types for `GET /uploads/{id}/tree` from docs/API.md §Uploads.
 *
 * Named `tree-types.ts` so this file does not conflict with the upload-shape
 * types T2.4 will land in `lib/api/uploads/types.ts` (see TASKS.md T2.5 file
 * ownership).
 */

import type { TreeFile } from '@/components/file-tree/types';

export type { TreeFile };

export type TreeResponse = {
  upload_id: string;
  root_name: string;
  files: TreeFile[];
};
