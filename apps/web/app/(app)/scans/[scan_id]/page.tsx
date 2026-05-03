'use client';

import Link from 'next/link';
import { useMemo } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';

import { ProgressBar } from '@/components/scan-progress/progress-bar';
import { ProgressHeader } from '@/components/scan-progress/progress-header';
import { RecentFilesTail } from '@/components/scan-progress/recent-files-tail';
import { SeverityCounters } from '@/components/scan-progress/severity-counters';
import { TerminalCard } from '@/components/scan-progress/terminal-card';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ApiError } from '@/lib/api/client';
import {
  useCancelScanMutation,
  useRecentScanFiles,
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

  const filesQuery = useRecentScanFiles(scanId, {
    enabled: !isTerminal,
    limit: 10,
  });
  const cancelMutation = useCancelScanMutation(scanId);

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
        onCancel={() => cancelMutation.mutate()}
      />

      {!isTerminal ? (
        <>
          <ProgressBar
            status={
              scan.status === 'pending' || scan.status === 'running'
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
          <SeverityCounters summary={scan.summary} />
          <TerminalCard scan={scan} />
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
