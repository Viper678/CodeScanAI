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
 * The copy follows three states so the user is never left guessing:
 *
 * - counts available -> "… also permanently remove its **N** scan(s) and
 *   **M** finding(s)."
 * - counts still loading -> ellipsis stand-ins so layout doesn't jump
 * - counts failed to load -> generic fallback (no numbers) — defensive only,
 *   the fetch errors silently rather than blocking the delete.
 */
type Args = {
  data: UploadDeleteImpact | undefined;
  isLoading: boolean;
  isError: boolean;
};

export function renderUploadDeleteWarning({
  data,
  isLoading,
  isError,
}: Args): ReactNode {
  if (isError) {
    return 'Deleting this upload will also permanently remove any scans and findings associated with it. This cannot be undone.';
  }
  if (isLoading || !data) {
    return (
      <>
        Deleting this upload will also permanently remove its <strong>…</strong>{' '}
        scan(s) and <strong>…</strong> finding(s). This cannot be undone.
      </>
    );
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
