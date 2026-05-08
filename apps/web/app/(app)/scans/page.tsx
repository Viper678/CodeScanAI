'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  AlertTriangle,
  ArrowRight,
  Loader2,
  RotateCcw,
  ScanLine,
} from 'lucide-react';
import { useState } from 'react';

import { EmptyState } from '@/components/empty-state';
import { DeleteScanButton } from '@/components/scans/delete-scan-button';
import { ScansFilterBar } from '@/components/scans/scans-filter-bar';
import { StatusPill } from '@/components/status-pill';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api/client';
import { useRerunScanMutation, useScansQuery } from '@/lib/api/scans/use-scans';
import { useScansFilters } from '@/lib/api/scans/use-scans-filters';
import type { ScanDetail, ScanStatus, ScanType } from '@/lib/api/scans/types';
import { formatShortDate } from '@/lib/format';
import { cn } from '@/lib/utils';

const PAGE_LIMIT = 20;

const TERMINAL: ReadonlySet<ScanStatus> = new Set([
  'completed',
  'failed',
  'cancelled',
]);

const SCAN_TYPE_LABEL: Record<ScanType, string> = {
  security: 'Security',
  bugs: 'Bug',
  keywords: 'Keyword',
};

export default function ScansPage() {
  const { filters, toggleStatus, clearAll } = useScansFilters();
  const query = useScansQuery({ limit: PAGE_LIMIT, status: filters.status });

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight">Scans</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Your scan history. Click a row to open its progress page.
          </p>
        </div>
        <Link
          href="/scans/new"
          className={cn(
            buttonVariants({ size: 'lg' }),
            'w-full bg-primary text-primary-foreground hover:bg-primary/90 md:w-auto',
          )}
        >
          New scan
          <ArrowRight className="size-4" />
        </Link>
      </div>

      <ScansFilterBar
        filters={filters}
        onToggleStatus={toggleStatus}
        onClear={clearAll}
      />

      {query.isPending ? (
        <ListSkeleton label="Loading scans…" />
      ) : query.error ? (
        <ErrorPanel
          message={query.error.message}
          onRetry={() => {
            void query.refetch();
          }}
        />
      ) : query.data.items.length === 0 ? (
        filters.status.length > 0 ? (
          <EmptyState
            icon={ScanLine}
            title="No scans match these filters"
            description="Try clearing the status filter to see your full scan history."
          />
        ) : (
          <EmptyState
            icon={ScanLine}
            title="No scans yet"
            description="Create your first static scan to see findings, severity badges, and progress surfaces appear here."
            action={{
              href: '/scans/new',
              label: 'Run your first scan',
            }}
          />
        )
      ) : (
        <ScansList items={query.data.items} total={query.data.total} />
      )}
    </div>
  );
}

type ScansListProps = {
  items: ScanDetail[];
  total: number;
};

function ScansList({ items, total }: Readonly<ScansListProps>) {
  return (
    <div className="space-y-3">
      <ul className="space-y-2" data-testid="scans-list">
        {items.map((scan) => (
          <li key={scan.id}>
            <ScanRow scan={scan} />
          </li>
        ))}
      </ul>
      {total > items.length ? (
        <p className="text-xs text-muted-foreground">
          Showing first {items.length} of {total} — pagination lands later.
        </p>
      ) : null}
    </div>
  );
}

type ScanRowProps = {
  scan: ScanDetail;
};

/**
 * Map a re-run failure to a tight inline message. The two we surface
 * differently are 422 with `unprocessable_rerun` (source can't be replayed —
 * either no scan_files at all or every file vanished) and the generic
 * fall-through. Network / 500s use the API-provided message.
 */
function rerunErrorText(err: ApiError): string {
  if (err.code === 'unprocessable_rerun') {
    return 'Source can no longer be re-run (files removed).';
  }
  return err.message || 'Could not re-run this scan.';
}

function ScanRow({ scan }: Readonly<ScanRowProps>) {
  const router = useRouter();
  const isTerminal = TERMINAL.has(scan.status);
  const progressText = isTerminal
    ? '—'
    : `${scan.progress_done} / ${scan.progress_total}`;
  const dateIso = scan.created_at;

  // Local error surface — kept per-row so a failure on one re-run doesn't
  // wipe inline errors on a sibling row mid-toast-style.
  const [errorText, setErrorText] = useState<string | null>(null);
  const rerun = useRerunScanMutation();

  // Terminal-only: re-running a pending/running scan is a no-op intent and
  // would race the worker — same rule the API would gladly enforce, but
  // keeping the button hidden keeps the UI honest.
  const canRerun = isTerminal;

  const handleRerun = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setErrorText(null);
    rerun.mutate(scan.id, {
      onError: (err) => {
        setErrorText(rerunErrorText(err));
      },
      onSuccess: (data) => {
        router.push(`/scans/${data.id}`);
      },
    });
  };

  return (
    <div className="space-y-1">
      <div
        data-testid={`scan-row-${scan.id}`}
        className={cn(
          'group/row relative flex items-center justify-between gap-4 rounded-2xl border border-border/80 bg-card/60 px-4 py-3',
          'transition-colors hover:border-border hover:bg-card',
          'focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2',
        )}
      >
        {/*
          The row's main click target is the link to the progress page. We
          can't nest a button inside an anchor (invalid HTML), so the link
          is laid out as an absolute overlay with the action button rendered
          above it via z-index — same pattern shadcn / radix recommends.
        */}
        <Link
          href={`/scans/${scan.id}`}
          aria-label={`Open scan ${scan.name ?? 'Unnamed scan'}`}
          className="absolute inset-0 rounded-2xl focus:outline-none"
        />
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <ScanLine className="size-4" aria-hidden="true" />
          </span>
          <div className="flex min-w-0 items-center gap-3">
            <p className="truncate text-sm font-medium text-foreground">
              {scan.name ?? 'Unnamed scan'}
            </p>
            <StatusPill status={scan.status} />
          </div>
        </div>
        <div className="relative z-10 flex shrink-0 items-center gap-3">
          <div className="hidden items-center gap-1.5 md:flex">
            {scan.scan_types.map((type) => (
              <Badge
                key={type}
                variant="outline"
                className="rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide"
              >
                {SCAN_TYPE_LABEL[type]}
              </Badge>
            ))}
          </div>
          <span className="hidden text-xs tabular-nums text-muted-foreground md:inline">
            {progressText}
          </span>
          <span className="hidden whitespace-nowrap text-xs text-muted-foreground md:inline">
            {formatShortDate(dateIso)}
          </span>
          {canRerun ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid={`scan-row-${scan.id}-rerun`}
              onClick={handleRerun}
              disabled={rerun.isPending}
              aria-label={`Re-run ${scan.name ?? 'scan'}`}
              className="h-7 gap-1 px-2 text-xs"
            >
              {rerun.isPending ? (
                <Loader2 className="size-3 animate-spin" aria-hidden="true" />
              ) : (
                <RotateCcw className="size-3" aria-hidden="true" />
              )}
              Re-run
            </Button>
          ) : null}
          <DeleteScanButton scanId={scan.id} scanName={scan.name ?? 'scan'} />
        </div>
      </div>
      {errorText ? (
        <p
          data-testid={`scan-row-${scan.id}-rerun-error`}
          role="alert"
          className="px-1 text-xs text-red-600 dark:text-red-300"
        >
          {errorText}
        </p>
      ) : null}
    </div>
  );
}

function ListSkeleton({ label }: Readonly<{ label: string }>) {
  return (
    <div className="flex items-center gap-3 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

type ErrorPanelProps = {
  message: string;
  onRetry: () => void;
};

function ErrorPanel({ message, onRetry }: Readonly<ErrorPanelProps>) {
  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          <AlertTriangle
            className="size-4 text-muted-foreground"
            aria-hidden="true"
          />
          Could not load scans.
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{message}</p>
        <div className="flex justify-end">
          <Button variant="outline" onClick={onRetry}>
            Retry
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
