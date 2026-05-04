'use client';

import { useSearchParams } from 'next/navigation';

import { FileViewerPage } from '@/components/file-viewer/file-viewer-page';

type RouteProps = {
  params: { upload_id: string; file_id: string };
};

/**
 * Read-only file viewer route (T4.3).
 *
 * URL contract:
 *   /uploads/{upload_id}/files/{file_id}?scan_id={scan_id}&line={line}
 *
 * - `scan_id` (optional) scopes the sidebar's per-file findings list.
 *   Without it the editor still renders, just with an empty sidebar.
 * - `line` (optional) is the 1-indexed line to scroll into view. Garbage
 *   values are ignored (we only forward strictly-positive integers).
 *
 * The route is a thin wrapper around `FileViewerPage` because the page
 * component is itself a client component — keeping the route file at
 * the smallest possible footprint helps Next's compiler tree-shake.
 */
export default function FileViewerRoute({ params }: Readonly<RouteProps>) {
  const search = useSearchParams();
  const scanId = search?.get('scan_id') ?? null;
  const initialLine = parseLine(search?.get('line') ?? null);

  return (
    <FileViewerPage
      uploadId={params.upload_id}
      fileId={params.file_id}
      scanId={scanId}
      initialLine={initialLine}
    />
  );
}

function parseLine(raw: string | null): number | null {
  if (raw === null || raw === '') return null;
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed) || parsed < 1) return null;
  return parsed;
}
