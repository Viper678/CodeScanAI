'use client';

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import type { ScanStatus } from '@/lib/api/scans/types';
import { formatEta } from '@/lib/scan-progress/eta';

type ProgressBarProps = {
  status: Extract<ScanStatus, 'pending' | 'running'>;
  done: number;
  total: number;
  /** ETA in milliseconds, or `null` while we don't have enough samples. */
  etaMs: number | null;
};

const STATUS_LABELS: Record<ProgressBarProps['status'], string> = {
  pending: 'Queued…',
  running: 'Scanning…',
};

/** Determinate progress bar with counter + ETA. */
export function ProgressBar({
  status,
  done,
  total,
  etaMs,
}: Readonly<ProgressBarProps>) {
  const pct = total > 0 ? (done / total) * 100 : 0;
  const counter = `${done} / ${total}`;
  const etaLabel =
    etaMs === null ? 'Estimating ETA…' : `ETA ${formatEta(etaMs)}`;

  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="text-base font-medium">Progress</CardTitle>
        <CardDescription>{STATUS_LABELS[status]}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Progress value={pct} aria-label="Scan progress" />
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span data-testid="progress-counter" className="font-mono">
            {counter}
          </span>
          <span data-testid="progress-eta">{etaLabel}</span>
        </div>
      </CardContent>
    </Card>
  );
}
