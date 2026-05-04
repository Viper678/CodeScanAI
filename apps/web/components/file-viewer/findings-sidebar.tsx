'use client';

import { Loader2 } from 'lucide-react';

import { SeverityDot } from '@/components/findings/severity-dot';
import type { Finding } from '@/lib/api/findings/types';
import { cn } from '@/lib/utils';

const SCAN_TYPE_LABEL = {
  bugs: 'Bugs',
  keywords: 'Keywords',
  security: 'Security',
} as const;

type FindingsSidebarProps = {
  /**
   * Findings on this file. Pre-filtered by the parent — the sidebar
   * doesn't refilter, so the parent owns the order (severity rank ASC).
   */
  findings: Finding[];
  /** ID of the currently-selected finding (for the active row state). */
  selectedId: string | null;
  /** Click / keyboard activation hands the line back to the editor. */
  onSelect: (finding: Finding) => void;
  /** True while the sidebar is fetching its initial findings list. */
  isLoading: boolean;
  /**
   * Absent ``scanId`` → the sidebar is informational only. We render a
   * hint so the user understands why no list is shown (rather than an
   * empty container they assume is broken).
   */
  hasScanContext: boolean;
};

/**
 * Right-side panel listing per-file findings, with severity dot, title,
 * line, and scan type. Clicking a row scrolls the editor to the line and
 * marks the row active. Keyboard nav (Enter/Space on a focused row) does
 * the same — same pattern as the findings table to keep the muscle
 * memory consistent.
 */
export function FindingsSidebar({
  findings,
  selectedId,
  onSelect,
  isLoading,
  hasScanContext,
}: Readonly<FindingsSidebarProps>) {
  if (!hasScanContext) {
    return (
      <aside
        data-testid="findings-sidebar"
        className="flex h-full flex-col border-l border-border/60 bg-card/40 p-4 text-sm text-muted-foreground"
      >
        <p>Open a file from a scan results page to see its findings here.</p>
      </aside>
    );
  }

  if (isLoading) {
    return (
      <aside
        data-testid="findings-sidebar"
        className="flex h-full flex-col items-center justify-center border-l border-border/60 bg-card/40 p-4 text-sm text-muted-foreground"
      >
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        <span className="mt-2">Loading findings…</span>
      </aside>
    );
  }

  return (
    <aside
      data-testid="findings-sidebar"
      className="flex h-full flex-col border-l border-border/60 bg-card/40"
    >
      <header className="border-b border-border/60 px-4 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Findings ({findings.length})
      </header>
      {findings.length === 0 ? (
        <div className="px-4 py-6 text-sm text-muted-foreground">
          No findings on this file.
        </div>
      ) : (
        <ul role="list" className="divide-y divide-border/60 overflow-y-auto">
          {findings.map((finding) => {
            const lineLabel =
              finding.line_start === null ? '—' : String(finding.line_start);
            const isActive = selectedId === finding.id;
            return (
              <li key={finding.id}>
                <button
                  type="button"
                  data-testid={`sidebar-item-${finding.id}`}
                  data-active={isActive ? 'true' : 'false'}
                  onClick={() => onSelect(finding)}
                  className={cn(
                    'flex w-full items-start gap-3 px-4 py-3 text-left text-sm outline-none transition-colors hover:bg-muted/40 focus-visible:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring/40',
                    isActive && 'bg-muted/50',
                  )}
                >
                  <SeverityDot severity={finding.severity} className="mt-1.5" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-foreground">
                      {finding.title}
                    </span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {SCAN_TYPE_LABEL[finding.scan_type]} · line {lineLabel}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
