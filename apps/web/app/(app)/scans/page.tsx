'use client';

import Link from 'next/link';
import { AlertTriangle, ArrowRight, Loader2, ScanLine } from 'lucide-react';

import { EmptyState } from '@/components/empty-state';
import { StatusPill } from '@/components/status-pill';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useScansQuery } from '@/lib/api/scans/use-scans';
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
  const query = useScansQuery({ limit: PAGE_LIMIT });

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
        <EmptyState
          icon={ScanLine}
          title="No scans yet"
          description="Create your first static scan to see findings, severity badges, and progress surfaces appear here."
          action={{
            href: '/scans/new',
            label: 'Run your first scan',
          }}
        />
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

function ScanRow({ scan }: Readonly<ScanRowProps>) {
  const isTerminal = TERMINAL.has(scan.status);
  const progressText = isTerminal
    ? '—'
    : `${scan.progress_done} / ${scan.progress_total}`;
  // ScanDetail does not yet ship `created_at`; fall back to started/finished
  // so the right-hand timestamp still has something meaningful.
  const dateIso =
    scan.created_at ?? scan.started_at ?? scan.finished_at ?? null;

  return (
    <Link
      href={`/scans/${scan.id}`}
      data-testid={`scan-row-${scan.id}`}
      className={cn(
        'flex items-center justify-between gap-4 rounded-2xl border border-border/80 bg-card/60 px-4 py-3',
        'transition-colors hover:border-border hover:bg-card focus-visible:outline-none',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
      )}
    >
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
      <div className="flex shrink-0 items-center gap-3">
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
      </div>
    </Link>
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
