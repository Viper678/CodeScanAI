'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams, useSearchParams } from 'next/navigation';

import { FileTree } from '@/components/file-tree/file-tree';
import type { TreeFile } from '@/components/file-tree/types';
import { useUploadTree } from '@/lib/api/uploads/tree';

import { generateFixture } from './fixture';

const EMPTY_FILES: ReadonlyArray<TreeFile> = [];

/**
 * Dual-purpose page: the user-facing tree view that the Uploads list links
 * to (where users choose which files to scan), and a developer playground
 * for the FileTree component. The synthetic-fixture query params
 * (`?fixture=10k|1k|small`) remain available for perf testing but are no
 * longer surfaced in the user-facing copy.
 */
export default function TreePreviewPage() {
  const params = useParams<{ upload_id: string }>();
  const searchParams = useSearchParams();
  const fixture = searchParams.get('fixture');
  const uploadId = params?.upload_id;

  const fixtureFiles = useMemo<TreeFile[] | null>(() => {
    if (fixture === '10k') return generateFixture(10_000);
    if (fixture === '1k') return generateFixture(1_000);
    if (fixture === 'small') return generateFixture(50);
    return null;
  }, [fixture]);

  const { data, isLoading, error } = useUploadTree(
    fixtureFiles ? undefined : uploadId,
  );

  const files = useMemo<ReadonlyArray<TreeFile>>(
    () => fixtureFiles ?? data?.files ?? EMPTY_FILES,
    [fixtureFiles, data],
  );
  const rootName = fixtureFiles
    ? `synthetic-${fixture}`
    : (data?.root_name ?? 'upload');

  // Initial selection lives in component state so the user can experiment
  // freely on the demo page. Production callers (the wizard) will own this.
  const [selection, setSelection] = useState<Set<string>>(new Set());

  // Seed with the default selection (all non-excluded) every time the file
  // list reference changes — i.e. after the fetch resolves or the fixture
  // toggles. Intentionally one-shot per files reference.
  useEffect(() => {
    const next = new Set<string>();
    for (const f of files) {
      if (!f.is_excluded_by_default) next.add(f.id);
    }
    setSelection(next);
  }, [files]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-semibold tracking-tight">
          Choose files to scan
        </h2>
      </div>

      {!fixtureFiles && isLoading && (
        <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
          Loading tree…
        </div>
      )}

      {!fixtureFiles && error && (
        <div className="rounded-lg border border-border bg-muted/40 p-6 text-sm text-foreground">
          Failed to load the upload tree:{' '}
          <span className="text-muted-foreground">{error.message}</span>
        </div>
      )}

      {(fixtureFiles || data) && (
        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <FileTree
            files={files}
            selection={selection}
            onSelectionChange={setSelection}
            height={560}
          />

          <aside className="rounded-lg border border-border bg-card p-4 text-sm">
            <p className="font-semibold">{rootName}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {files.length.toLocaleString()} files indexed
            </p>
            <div className="mt-4 space-y-1 text-xs text-muted-foreground">
              <p>
                <strong className="text-foreground">{selection.size}</strong>{' '}
                selected (out of{' '}
                {files.filter((f) => !f.is_excluded_by_default).length}{' '}
                non-excluded)
              </p>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
