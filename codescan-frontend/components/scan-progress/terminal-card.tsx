'use client';

import Link from 'next/link';

import { buttonVariants } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import type { ScanDetail } from '@/lib/api/scans/types';
import { cn } from '@/lib/utils';

type TerminalCardProps = {
  scan: ScanDetail;
};

const TERMINAL_TITLES = {
  cancelled: 'Scan cancelled',
  completed: 'Scan complete',
  failed: 'Scan failed',
} as const;

const TERMINAL_DESCRIPTIONS = {
  cancelled: 'Scan was cancelled.',
  completed: 'Findings are ready below.',
  failed: 'The scan stopped before finishing.',
} as const;

/**
 * Final-state card shown once a scan reaches `completed` / `failed` /
 * `cancelled`. Counters are frozen by the caller (we just render whatever
 * `scan.summary` carries at the time we mount). The actual findings table
 * is rendered by the parent page next to this card on `completed`.
 */
export function TerminalCard({ scan }: Readonly<TerminalCardProps>) {
  if (
    scan.status !== 'completed' &&
    scan.status !== 'failed' &&
    scan.status !== 'cancelled'
  ) {
    return null;
  }
  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="text-base font-medium">
          {TERMINAL_TITLES[scan.status]}
        </CardTitle>
        <CardDescription>{TERMINAL_DESCRIPTIONS[scan.status]}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {scan.status === 'failed' && scan.error ? (
          <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 font-mono text-xs text-red-600 dark:text-red-300">
            {scan.error}
          </p>
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
