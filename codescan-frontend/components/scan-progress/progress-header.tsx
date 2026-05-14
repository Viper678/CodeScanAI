'use client';

import { Loader2, X } from 'lucide-react';
import type { ReactNode } from 'react';

import { StatusPill } from '@/components/status-pill';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { ScanDetail, ScanType } from '@/lib/api/scans/types';

const TYPE_LABELS: Record<ScanType, string> = {
  bugs: 'Bugs',
  keywords: 'Keywords',
  security: 'Security',
};

type ProgressHeaderProps = {
  scan: ScanDetail;
  /** True iff a cancel mutation is in flight (button should disable + spin). */
  cancelling: boolean;
  onCancel: () => void;
  /** Extra action buttons rendered after the Cancel button. Use for the
   *  data-retention delete button in the live progress view. */
  actions?: ReactNode;
};

/**
 * Top of the progress page: scan name + status pill + scan-type badges, and
 * (when cancellable) a Cancel button. Re-run / Export are reserved for Phase 4
 * — see docs/UI_DESIGN.md §`/scans/{id}`.
 */
export function ProgressHeader({
  scan,
  cancelling,
  onCancel,
  actions,
}: Readonly<ProgressHeaderProps>) {
  const cancellable = scan.status === 'pending' || scan.status === 'running';
  const displayName = scan.name?.trim().length ? scan.name : 'Scan';
  const hasTrailingActions = cancellable || actions !== undefined;

  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-3xl font-semibold tracking-tight">
            {displayName}
          </h2>
          <StatusPill status={scan.status} />
        </div>
        <div className="flex flex-wrap gap-2">
          {scan.scan_types.map((type) => (
            <Badge key={type} variant="secondary">
              {TYPE_LABELS[type]}
            </Badge>
          ))}
        </div>
      </div>
      {hasTrailingActions ? (
        <div className="flex flex-wrap items-center gap-2">
          {cancellable ? (
            <Button
              type="button"
              variant="outline"
              onClick={onCancel}
              disabled={cancelling}
            >
              {cancelling ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <X className="size-4" aria-hidden="true" />
              )}
              {cancelling ? 'Cancelling…' : 'Cancel'}
            </Button>
          ) : null}
          {actions}
        </div>
      ) : null}
    </div>
  );
}
