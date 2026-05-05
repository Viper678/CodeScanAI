'use client';

import { AlertTriangle, ListFilter, Loader2 } from 'lucide-react';
import { useMemo, useState } from 'react';

import {
  FINDINGS_GRID_COLS,
  FindingsRow,
} from '@/components/findings/findings-row';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api/client';
import { useFindingsInfinite } from '@/lib/api/findings/use-findings';
import type { Finding, FindingsFilters } from '@/lib/api/findings/types';

type FindingsTableProps = {
  scanId: string;
  filters: FindingsFilters;
  /**
   * Upload id, threaded down so each row can build a fully-qualified link
   * to the file viewer (`/uploads/{upload_id}/files/{file_id}?...`). Comes
   * from the parent scan detail (`scan.upload_id`); kept as a prop so this
   * component stays free of scan-fetch state.
   */
  uploadId: string;
};

/**
 * Build the file-viewer href for a finding. Includes the originating
 * `scan_id` so the viewer's sidebar can scope the per-file findings list,
 * and `line` so it can scroll to the offending position on mount. We only
 * append `line` when `line_start` is non-null — the viewer treats an
 * absent param as "open at the top".
 */
function buildFileHref({
  uploadId,
  scanId,
  fileId,
  lineStart,
}: {
  uploadId: string;
  scanId: string;
  fileId: string;
  lineStart: number | null;
}): string {
  const search = new URLSearchParams({ scan_id: scanId });
  if (lineStart !== null) {
    search.set('line', String(lineStart));
  }
  return `/uploads/${uploadId}/files/${fileId}?${search.toString()}`;
}

/**
 * Findings table with cursor-paginated infinite scroll, expandable rows, and
 * an explicit "Load more" button (no scroll-spy in v1 — see UI_DESIGN.md
 * §pagination). Loading / empty / error follow the patterns in the same doc.
 *
 * Row expansion is local component state (single-row open at a time) — we
 * keep it in `useState` rather than the URL because it's transient and would
 * otherwise spam the back stack on every click.
 */
export function FindingsTable({
  scanId,
  filters,
  uploadId,
}: Readonly<FindingsTableProps>) {
  const query = useFindingsInfinite(scanId, filters);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const items = useMemo<Finding[]>(
    () => query.data?.pages.flatMap((page) => page.items) ?? [],
    [query.data],
  );
  const total = query.data?.pages[0]?.total ?? null;

  if (query.isPending) {
    return <FindingsLoading />;
  }

  if (query.error) {
    return (
      <FindingsError
        message={
          query.error instanceof ApiError
            ? query.error.message
            : 'Could not load findings.'
        }
        onRetry={() => query.refetch()}
      />
    );
  }

  if (items.length === 0) {
    return <FindingsEmpty hasFilters={hasActiveFilters(filters)} />;
  }

  return (
    <section
      data-testid="findings-table"
      className="overflow-hidden rounded-lg border border-border/80 bg-card/40"
    >
      <header
        className={`grid ${FINDINGS_GRID_COLS} items-center gap-3 border-b border-border/80 bg-muted/30 px-4 py-2 text-xs font-medium uppercase tracking-wide text-muted-foreground`}
      >
        <span className="sr-only">Severity</span>
        <span>File</span>
        <span>Line</span>
        <span>Type</span>
        <span>Title</span>
      </header>

      <div role="list" className="divide-y-0">
        {items.map((finding) => (
          <FindingsRow
            key={finding.id}
            finding={finding}
            expanded={expandedId === finding.id}
            onToggle={() =>
              setExpandedId((prev) => (prev === finding.id ? null : finding.id))
            }
            fileHref={buildFileHref({
              fileId: finding.file.id,
              lineStart: finding.line_start,
              scanId,
              uploadId,
            })}
          />
        ))}
      </div>

      <footer className="flex items-center justify-between gap-3 border-t border-border/80 bg-card/60 px-4 py-3 text-xs text-muted-foreground">
        <span data-testid="findings-count-summary">
          Showing {items.length}
          {total !== null ? ` of ${total}` : ''} findings
        </span>
        {query.hasNextPage ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
            data-testid="findings-load-more"
          >
            {query.isFetchingNextPage ? (
              <>
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                Loading…
              </>
            ) : (
              'Load more'
            )}
          </Button>
        ) : null}
      </footer>
    </section>
  );
}

function hasActiveFilters(filters: FindingsFilters): boolean {
  return (
    filters.severity.length > 0 ||
    filters.scan_type.length > 0 ||
    filters.file_id !== null
  );
}

function FindingsLoading() {
  return (
    <Card className="border-border/80">
      <CardContent className="py-12">
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          Loading findings…
        </div>
      </CardContent>
    </Card>
  );
}

type FindingsErrorProps = {
  message: string;
  onRetry: () => void;
};

function FindingsError({ message, onRetry }: Readonly<FindingsErrorProps>) {
  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          <AlertTriangle
            className="size-4 text-muted-foreground"
            aria-hidden="true"
          />
          Could not load findings.
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{message}</p>
        <div className="flex justify-end">
          <Button type="button" variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function FindingsEmpty({ hasFilters }: Readonly<{ hasFilters: boolean }>) {
  return (
    <Card className="border-dashed border-border/80">
      <CardContent className="py-14">
        <div className="mx-auto flex max-w-md flex-col items-center gap-3 text-center">
          <ListFilter
            className="size-6 text-muted-foreground"
            aria-hidden="true"
          />
          <p className="text-base font-medium">
            {hasFilters ? 'No findings match these filters.' : 'No findings.'}
          </p>
          <p className="text-sm text-muted-foreground">
            {hasFilters
              ? 'Try removing a severity or scan type to broaden the results.'
              : 'This scan completed without surfacing any issues.'}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
