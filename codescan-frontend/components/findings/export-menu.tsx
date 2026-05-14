'use client';

import { ChevronDown, Download } from 'lucide-react';

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';
import { getExportUrl } from '@/lib/api/findings/client';
import type { FindingsFilters } from '@/lib/api/findings/types';

type ExportMenuProps = {
  scanId: string;
  filters: FindingsFilters;
  /** Disable while no findings are loaded yet — see `disabledReason` for tooltip text. */
  disabled?: boolean;
};

/**
 * Export dropdown — JSON or CSV. Each item is a real `<a download>` so the
 * browser handles the streamed `Content-Disposition` response from the API
 * without bouncing through fetch (cookie auth means the session cookie is
 * sent automatically when the user clicks).
 *
 * The active filter set is forwarded so "Export filtered" matches what the
 * user sees in the table — same params the list endpoint uses.
 */
export function ExportMenu({
  scanId,
  filters,
  disabled = false,
}: Readonly<ExportMenuProps>) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="outline"
            size="sm"
            disabled={disabled}
            data-testid="export-menu-trigger"
          >
            <Download className="size-3.5" aria-hidden="true" />
            Export
            <ChevronDown className="size-3.5" aria-hidden="true" />
          </Button>
        }
      />
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          render={
            <a
              href={getExportUrl(scanId, 'json', filters)}
              download={`scan-${scanId}.json`}
              data-testid="export-link-json"
            >
              Export as JSON
            </a>
          }
        />
        <DropdownMenuItem
          render={
            <a
              href={getExportUrl(scanId, 'csv', filters)}
              download={`scan-${scanId}.csv`}
              data-testid="export-link-csv"
            >
              Export as CSV
            </a>
          }
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
