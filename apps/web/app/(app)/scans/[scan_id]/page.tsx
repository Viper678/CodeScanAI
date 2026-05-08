'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';

import { ExportMenu } from '@/components/findings/export-menu';
import { FindingsFilterBar } from '@/components/findings/findings-filter-bar';
import { FindingsTable } from '@/components/findings/findings-table';
import { ProgressBar } from '@/components/scan-progress/progress-bar';
import { ProgressHeader } from '@/components/scan-progress/progress-header';
import { RecentFilesTail } from '@/components/scan-progress/recent-files-tail';
import { SeverityCounters } from '@/components/scan-progress/severity-counters';
import { TerminalCard } from '@/components/scan-progress/terminal-card';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api/client';
import { useFindingsFilters } from '@/lib/api/findings/use-findings-filters';
import {
  useCancelScanMutation,
  usePauseScanMutation,
  useRecentScanFiles,
  useResumeScanMutation,
  useScanPolling,
} from '@/lib/api/scans/use-scans';
import type { ScanStatus } from '@/lib/api/scans/types';
import { computeEta } from '@/lib/scan-progress/eta';
import { cn } from '@/lib/utils';

const TERMINAL: ReadonlySet<ScanStatus> = new Set([
  'completed',
  'failed',
  'cancelled',
]);

type ScanProgressPageProps = {
  params: { scan_id: string };
};

/** Live progress page — see docs/UI_DESIGN.md §`/scans/{id}`. */
export default function ScanProgressPage({
  params,
}: Readonly<ScanProgressPageProps>) {
  const scanId = params.scan_id;
  const scanQuery = useScanPolling(scanId);
  const scan = scanQuery.data ?? null;
  const isTerminal = scan ? TERMINAL.has(scan.status) : false;

  // Gate the recent-files poll on a successful scan fetch. If the scan
  // request 404s or errors, !isTerminal is still true (no data → not a
  // terminal status), which would otherwise leave us hammering
  // /scans/{id}/files every 3s while the error panel renders.
  const filesQuery = useRecentScanFiles(scanId, {
    enabled: scanQuery.isSuccess && !isTerminal,
    limit: 10,
  });
  const cancelMutation = useCancelScanMutation(scanId);
  const pauseMutation = usePauseScanMutation(scanId);
  const resumeMutation = useResumeScanMutation(scanId);
  const { filters, toggleSeverity, toggleScanType, clearAll } =
    useFindingsFilters();

  // Per-action error surface — kept inline (no toast lib in this codebase
  // yet; mirrors the inline-error pattern used by the re-run button on
  // /scans). Cleared whenever the user clicks a fresh action.
  const [actionError, setActionError] = useState<string | null>(null);

  const handlePause = () => {
    setActionError(null);
    pauseMutation.mutate(undefined, {
      onError: (err) => {
        setActionError(err.message || 'Could not pause this scan.');
      },
    });
  };

  const handleResume = () => {
    setActionError(null);
    resumeMutation.mutate(undefined, {
      onError: (err) => {
        // 503 leaves the scan in `paused` server-side; surface a concrete
        // "try again" message rather than the generic API string.
        if (err.code === 'queue_unavailable') {
          setActionError(
            'Queue unavailable, try again in a moment. Scan is still paused.',
          );
          return;
        }
        setActionError(err.message || 'Could not resume this scan.');
      },
    });
  };

  const handleCancel = () => {
    setActionError(null);
    cancelMutation.mutate();
  };

  // Latencies feed the rolling-average ETA. Filter to finalized rows only.
  const etaMs = useMemo(() => {
    if (!scan) return null;
    const remaining = Math.max(0, scan.progress_total - scan.progress_done);
    const latencies = (filesQuery.data?.items ?? [])
      .filter((item) => item.latency_ms !== null)
      .map((item) => item.latency_ms as number);
    return computeEta({ latencies, remaining });
  }, [scan, filesQuery.data]);

  // Loading state — first paint, no data yet.
  if (scanQuery.isPending) {
    return (
      <div className="space-y-8">
        <SkeletonHeader />
      </div>
    );
  }

  // Error state — 404 or network. Surface the same muted card for both.
  if (scanQuery.error) {
    const notFound =
      scanQuery.error instanceof ApiError && scanQuery.error.status === 404;
    return (
      <ErrorPanel
        title={notFound ? 'Scan not found.' : 'Could not load this scan.'}
        message={notFound ? null : scanQuery.error.message}
      />
    );
  }

  if (!scan) {
    // Should never reach here, but keep TS happy.
    return <ErrorPanel title="Scan not found." message={null} />;
  }

  return (
    <div className="space-y-8">
      <ProgressHeader
        scan={scan}
        cancelling={cancelMutation.isPending}
        pausing={pauseMutation.isPending}
        resuming={resumeMutation.isPending}
        onCancel={handleCancel}
        onPause={handlePause}
        onResume={handleResume}
      />

      {actionError ? (
        <p
          data-testid="scan-action-error"
          role="alert"
          className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-300"
        >
          {actionError}
        </p>
      ) : null}

      {!isTerminal ? (
        <>
          <ProgressBar
            status={
              scan.status === 'pending' ||
              scan.status === 'running' ||
              scan.status === 'paused'
                ? scan.status
                : 'pending'
            }
            done={scan.progress_done}
            total={scan.progress_total}
            etaMs={etaMs}
          />
          <SeverityCounters summary={scan.summary} />
          <RecentFilesTail
            items={filesQuery.data?.items ?? []}
            isLoading={filesQuery.isPending}
          />
        </>
      ) : (
        <>
          <div className="flex items-center justify-between gap-3">
            <SeverityCounters summary={scan.summary} />
          </div>
          <TerminalCard scan={scan} />
          {scan.status === 'completed' ? (
            <section
              data-testid="findings-section"
              className="space-y-4 border-t border-border/60 pt-6"
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Findings</h2>
                  <p className="text-sm text-muted-foreground">
                    Filter by severity or scan type, then click a row to expand
                    the snippet.
                  </p>
                </div>
                <ExportMenu scanId={scan.id} filters={filters} />
              </div>
              <FindingsFilterBar
                filters={filters}
                onToggleSeverity={toggleSeverity}
                onToggleScanType={toggleScanType}
                onClear={clearAll}
              />
              <FindingsTable
                scanId={scan.id}
                filters={filters}
                uploadId={scan.upload_id}
              />
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}

function SkeletonHeader() {
  return (
    <div className="flex items-center gap-3 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      Loading scan…
    </div>
  );
}

type ErrorPanelProps = {
  title: string;
  message: string | null;
};

function ErrorPanel({ title, message }: Readonly<ErrorPanelProps>) {
  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          <AlertTriangle
            className="size-4 text-muted-foreground"
            aria-hidden="true"
          />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {message ? (
          <p className="text-sm text-muted-foreground">{message}</p>
        ) : null}
        <div className="flex justify-end">
          <Link
            href="/scans"
            className={cn(buttonVariants({ variant: 'outline' }))}
          >
            Back to scans
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
