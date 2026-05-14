'use client';

import { X } from 'lucide-react';

import { SeverityDot } from '@/components/findings/severity-dot';
import { Button } from '@/components/ui/button';
import type { FindingsFilters } from '@/lib/api/findings/types';
import type { ScanType, Severity } from '@/lib/api/scans/types';
import { cn } from '@/lib/utils';

const SEVERITIES: ReadonlyArray<Severity> = [
  'critical',
  'high',
  'medium',
  'low',
  'info',
];
const SCAN_TYPES: ReadonlyArray<{ id: ScanType; label: string }> = [
  { id: 'security', label: 'Security' },
  { id: 'bugs', label: 'Bugs' },
  { id: 'keywords', label: 'Keywords' },
];

type FindingsFilterBarProps = {
  filters: FindingsFilters;
  onToggleSeverity: (severity: Severity) => void;
  onToggleScanType: (scanType: ScanType) => void;
  onClear: () => void;
};

/**
 * Two horizontal chip rows for severity + scan type, plus a "Clear all"
 * button that becomes available once any filter is active.
 *
 * Per docs/UI_DESIGN.md `/scans/{id}` results section: severity / scan-type /
 * file-path filters. File-path search lands with T4.3 once we have the file
 * picker tied into the file viewer; for now the file_id filter is set
 * programmatically when the user clicks a finding's file link off the table
 * (and round-trips via the URL).
 */
export function FindingsFilterBar({
  filters,
  onToggleSeverity,
  onToggleScanType,
  onClear,
}: Readonly<FindingsFilterBarProps>) {
  const hasAny =
    filters.severity.length > 0 ||
    filters.scan_type.length > 0 ||
    filters.file_id !== null;

  return (
    <div
      data-testid="findings-filter-bar"
      className="flex flex-col gap-3 rounded-lg border border-border/80 bg-card/40 p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Severity
        </span>
        {SEVERITIES.map((severity) => {
          const active = filters.severity.includes(severity);
          return (
            <button
              key={severity}
              type="button"
              data-testid={`filter-severity-${severity}`}
              data-active={active ? 'true' : 'false'}
              aria-pressed={active}
              onClick={() => onToggleSeverity(severity)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium capitalize transition-colors',
                active
                  ? 'border-foreground/40 bg-foreground/10 text-foreground'
                  : 'border-border/80 bg-transparent text-muted-foreground hover:bg-muted/40',
              )}
            >
              <SeverityDot severity={severity} />
              {severity}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Type
        </span>
        {SCAN_TYPES.map(({ id, label }) => {
          const active = filters.scan_type.includes(id);
          return (
            <button
              key={id}
              type="button"
              data-testid={`filter-scan-type-${id}`}
              data-active={active ? 'true' : 'false'}
              aria-pressed={active}
              onClick={() => onToggleScanType(id)}
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

        {filters.file_id ? (
          <span
            data-testid="filter-file-active"
            className="inline-flex items-center gap-1.5 rounded-full border border-foreground/40 bg-foreground/10 px-2.5 py-1 text-xs text-foreground"
          >
            file: <span className="font-mono">{filters.file_id}</span>
          </span>
        ) : null}

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
