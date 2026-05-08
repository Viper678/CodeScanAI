'use client';

import { Loader2, Pause, Play, X } from 'lucide-react';

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
  /** True iff a pause mutation is in flight. */
  pausing: boolean;
  /** True iff a resume mutation is in flight. */
  resuming: boolean;
  onCancel: () => void;
  onPause: () => void;
  onResume: () => void;
};

/**
 * Top of the progress page: scan name + status pill + scan-type badges, plus
 * the pause/resume/cancel control set:
 *
 * - `running` → Pause + Cancel
 * - `paused`  → Resume + Cancel  (cancel-from-paused is supported by the API)
 * - `pending` → Cancel only      (worker hasn't started yet — pause is N/A)
 * - terminal  → no controls
 *
 * See docs/UI_DESIGN.md §`/scans/{id}` and docs/API.md §pause/resume.
 */
export function ProgressHeader({
  scan,
  cancelling,
  pausing,
  resuming,
  onCancel,
  onPause,
  onResume,
}: Readonly<ProgressHeaderProps>) {
  // Cancel is valid from pending/running/paused (paused→cancelled is direct
  // per docs/API.md §`POST /scans/{id}/cancel`).
  const cancellable =
    scan.status === 'pending' ||
    scan.status === 'running' ||
    scan.status === 'paused';
  const pausable = scan.status === 'running';
  const resumable = scan.status === 'paused';
  const displayName = scan.name?.trim().length ? scan.name : 'Scan';

  // Disable controls while ANY mutation is in flight so a double-click on
  // Pause doesn't race a Cancel click on the same row.
  const anyPending = cancelling || pausing || resuming;

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
      {cancellable || pausable || resumable ? (
        <div className="flex flex-wrap items-center gap-2">
          {pausable ? (
            <Button
              type="button"
              variant="outline"
              data-testid="scan-pause"
              onClick={onPause}
              disabled={anyPending}
            >
              {pausing ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <Pause className="size-4" aria-hidden="true" />
              )}
              {pausing ? 'Pausing…' : 'Pause'}
            </Button>
          ) : null}
          {resumable ? (
            <Button
              type="button"
              variant="outline"
              data-testid="scan-resume"
              onClick={onResume}
              disabled={anyPending}
            >
              {resuming ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <Play className="size-4" aria-hidden="true" />
              )}
              {resuming ? 'Resuming…' : 'Resume'}
            </Button>
          ) : null}
          {cancellable ? (
            <Button
              type="button"
              variant="outline"
              data-testid="scan-cancel"
              onClick={onCancel}
              disabled={anyPending}
            >
              {cancelling ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <X className="size-4" aria-hidden="true" />
              )}
              {cancelling ? 'Cancelling…' : 'Cancel'}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
