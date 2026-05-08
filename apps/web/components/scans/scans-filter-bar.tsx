'use client';

import { X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import type { ScansFilters, ScanStatus } from '@/lib/api/scans/types';
import { cn } from '@/lib/utils';

const STATUS_OPTIONS: ReadonlyArray<{ id: ScanStatus; label: string }> = [
  { id: 'pending', label: 'Pending' },
  { id: 'running', label: 'Running' },
  { id: 'paused', label: 'Paused' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
  { id: 'cancelled', label: 'Cancelled' },
];

type ScansFilterBarProps = {
  filters: ScansFilters;
  onToggleStatus: (status: ScanStatus) => void;
  onClear: () => void;
};

/**
 * Single horizontal chip row for status, plus a "Clear all" button that
 * appears once any filter is active. Mirrors the shape of T4.2's findings
 * filter bar so the two surfaces feel identical — same chip styling,
 * same `aria-pressed` semantics, same `data-testid` convention.
 *
 * `upload_id` is intentionally omitted from v1: a UUID picker is bad UX
 * with no upload-name surface yet (see `useScansFilters` docstring).
 */
export function ScansFilterBar({
  filters,
  onToggleStatus,
  onClear,
}: Readonly<ScansFilterBarProps>) {
  const hasAny = filters.status.length > 0;

  return (
    <div
      data-testid="scans-filter-bar"
      className="flex flex-col gap-3 rounded-lg border border-border/80 bg-card/40 p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Status
        </span>
        {STATUS_OPTIONS.map(({ id, label }) => {
          const active = filters.status.includes(id);
          return (
            <button
              key={id}
              type="button"
              data-testid={`filter-status-${id}`}
              data-active={active ? 'true' : 'false'}
              aria-pressed={active}
              onClick={() => onToggleStatus(id)}
              className={cn(
                'inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                active
                  ? 'border-foreground/40 bg-foreground/10 text-foreground'
                  : 'border-border/80 bg-transparent text-muted-foreground hover:bg-muted/40',
              )}
            >
              {label}
            </button>
          );
        })}

        {hasAny ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onClear}
            className="ml-auto h-7 gap-1 px-2 text-xs"
            data-testid="filter-clear"
          >
            <X className="size-3.5" aria-hidden="true" />
            Clear
          </Button>
        ) : null}
      </div>
    </div>
  );
}
