'use client';

import type { ReactNode } from 'react';

import type { UploadDeleteImpact } from '@/lib/api/uploads/use-upload';

/**
 * Builds the warning copy shown next to the Confirm/Cancel pair when the
 * user arms an upload delete. The server cascade through `scan` +
 * `scan_findings` is intentional (see docs/API.md §`DELETE /uploads/{id}`),
 * but the UI didn't surface it — leaving the user with no signal that
 * confirming would also wipe scans + findings tied to this upload.
 *
 * The copy follows four states so the user is never left guessing:
 *
 * - counts available + complete -> "… also permanently remove its **N**
 *   scan(s) and **M** finding(s)."
 * - counts available but incomplete (>100 scans paged) -> no-numbers fallback;
 *   we'd rather omit than understate, since the cascade is irreversible.
 * - counts in-flight (initial load OR refetch after re-arming) -> ellipsis
 *   stand-ins so layout doesn't jump. ``isFetching`` (not ``isLoading``)
 *   covers the refetch case where stale cached data would otherwise leak.
 * - counts failed to load -> generic fallback (no numbers) — defensive only,
 *   the fetch errors silently rather than blocking the delete.
 */
type Args = {
  data: UploadDeleteImpact | undefined;
  isFetching: boolean;
  isError: boolean;
};

const FALLBACK_COPY =
  'Deleting this upload will also permanently remove any scans and findings associated with it. This cannot be undone.';

export function renderUploadDeleteWarning({
  data,
  isFetching,
  isError,
}: Args): ReactNode {
  if (isError) {
    return FALLBACK_COPY;
  }
  if (isFetching || !data) {
    return (
      <>
        Deleting this upload will also permanently remove its <strong>…</strong>{' '}
        scan(s) and <strong>…</strong> finding(s). This cannot be undone.
      </>
    );
  }
  if (!data.complete) {
    return FALLBACK_COPY;
  }
  const { scanCount, findingCount } = data;
  return (
    <>
      Deleting this upload will also permanently remove its{' '}
      <strong>{scanCount}</strong> {scanCount === 1 ? 'scan' : 'scans'} and{' '}
      <strong>{findingCount}</strong>{' '}
      {findingCount === 1 ? 'finding' : 'findings'}. This cannot be undone.
    </>
  );
}
