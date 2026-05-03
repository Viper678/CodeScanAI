'use client';

import {
  AlertCircle,
  CheckCircle2,
  CircleDashed,
  Loader2,
  MinusCircle,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import type { ScanFileItem, ScanFileStatus } from '@/lib/api/scans/types';
import { cn } from '@/lib/utils';

const STATUS_META: Record<
  ScanFileStatus,
  { Icon: LucideIcon; className: string; label: string }
> = {
  done: {
    Icon: CheckCircle2,
    className: 'text-emerald-500',
    label: 'Done',
  },
  failed: {
    Icon: AlertCircle,
    className: 'text-red-500',
    label: 'Failed',
  },
  pending: {
    Icon: CircleDashed,
    className: 'text-muted-foreground',
    label: 'Pending',
  },
  running: {
    Icon: Loader2,
    className: 'text-sky-500 animate-spin',
    label: 'Running',
  },
  skipped: {
    Icon: MinusCircle,
    className: 'text-muted-foreground',
    label: 'Skipped',
  },
};

function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds - minutes * 60);
  return `${minutes}m ${rem}s`;
}

type RecentFilesTailProps = {
  items: ReadonlyArray<ScanFileItem>;
  /** True before we've received the first poll. */
  isLoading: boolean;
};

/** Tail log of the last N finalized scan_files. */
export function RecentFilesTail({
  items,
  isLoading,
}: Readonly<RecentFilesTailProps>) {
  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="text-base font-medium">Recent files</CardTitle>
        <CardDescription>
          Most-recently-finalized files in this scan.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Scanning… no files finalized yet.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {items.slice(0, 10).map((item) => {
              const meta = STATUS_META[item.status];
              const Icon = meta.Icon;
              return (
                <li
                  key={item.id}
                  className="flex items-center gap-3 rounded-md border border-border/60 bg-card/60 px-3 py-2 text-sm"
                >
                  <Icon
                    className={cn('size-4 shrink-0', meta.className)}
                    aria-label={meta.label}
                  />
                  <span
                    className="flex-1 truncate font-mono text-xs text-foreground"
                    title={item.path}
                  >
                    {item.path}
                  </span>
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    {item.latency_ms !== null
                      ? formatLatency(item.latency_ms)
                      : '—'}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
