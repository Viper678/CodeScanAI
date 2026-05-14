'use client';

import { Card, CardContent } from '@/components/ui/card';
import { SeverityBadge } from '@/components/severity-badge';
import type { ScanSummary, Severity } from '@/lib/api/scans/types';

const ORDER: ReadonlyArray<Severity> = [
  'critical',
  'high',
  'medium',
  'low',
  'info',
];

type SeverityCountersProps = {
  summary: ScanSummary;
};

/**
 * Five compact cards showing one count per severity. Missing keys default to
 * 0 since the API omits empty buckets (see ScanSummary type docstring).
 */
export function SeverityCounters({ summary }: Readonly<SeverityCountersProps>) {
  return (
    <div
      data-testid="severity-counters"
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5"
    >
      {ORDER.map((severity) => {
        const count = summary.by_severity[severity] ?? 0;
        return (
          <Card key={severity} size="sm" className="border-border/80">
            <CardContent className="flex items-center justify-between gap-2">
              <SeverityBadge severity={severity} />
              <span
                data-testid={`severity-count-${severity}`}
                className="font-mono text-lg font-semibold tabular-nums"
              >
                {count}
              </span>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
