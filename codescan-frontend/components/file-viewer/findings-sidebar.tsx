'use client';

import { Loader2 } from 'lucide-react';
import { useId, useState } from 'react';

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
  /**
   * Server-reported total for this file. When greater than `findings.length`
   * we render a truncation hint so the user isn't silently looking at a
   * partial list (the per-file query is single-page, capped at 200 — see
   * `useFindingsForFile`).
   */
  total: number | null;
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
 * marks the row active. The same click also toggles an inline disclosure
 * panel beneath the row that shows the finding's message, recommendation,
 * and rule/confidence — the editor only shows code, so without this the
 * user has to bounce back to the scan results page to read details.
 *
 * Single-row-open-at-a-time, mirroring the table's pattern. Active state
 * (driven by `selectedId` from the parent) is independent of expansion —
 * a row can be active without being expanded if the user navigated to it
 * via the gutter.
 */
export function FindingsSidebar({
  findings,
  total,
  selectedId,
  onSelect,
  isLoading,
  hasScanContext,
}: Readonly<FindingsSidebarProps>) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

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
        Findings ({findings.length}
        {total !== null && total > findings.length ? ` of ${total}` : ''})
      </header>
      {findings.length === 0 ? (
        <div className="px-4 py-6 text-sm text-muted-foreground">
          No findings on this file.
        </div>
      ) : (
        <ul role="list" className="divide-y divide-border/60 overflow-y-auto">
          {findings.map((finding) => (
            <SidebarItem
              key={finding.id}
              finding={finding}
              isActive={selectedId === finding.id}
              isExpanded={expandedId === finding.id}
              onClick={() => {
                onSelect(finding);
                setExpandedId((prev) =>
                  prev === finding.id ? null : finding.id,
                );
              }}
            />
          ))}
        </ul>
      )}
    </aside>
  );
}

type SidebarItemProps = {
  finding: Finding;
  isActive: boolean;
  isExpanded: boolean;
  onClick: () => void;
};

function SidebarItem({
  finding,
  isActive,
  isExpanded,
  onClick,
}: Readonly<SidebarItemProps>) {
  const detailsId = useId();
  const lineLabel =
    finding.line_start === null ? '—' : String(finding.line_start);
  const hasDetails =
    Boolean(finding.message) ||
    Boolean(finding.recommendation) ||
    Boolean(finding.rule_id) ||
    finding.confidence !== null;

  return (
    <li>
      <button
        type="button"
        data-testid={`sidebar-item-${finding.id}`}
        data-active={isActive ? 'true' : 'false'}
        aria-expanded={isExpanded}
        aria-controls={hasDetails ? detailsId : undefined}
        onClick={onClick}
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
      {isExpanded && hasDetails ? (
        <div
          id={detailsId}
          data-testid={`sidebar-details-${finding.id}`}
          className="space-y-3 bg-muted/10 px-4 py-3 text-sm"
        >
          {finding.message ? (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Message
              </p>
              <p className="mt-1 whitespace-pre-wrap text-foreground">
                {finding.message}
              </p>
            </div>
          ) : null}
          {finding.recommendation ? (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Recommendation
              </p>
              <p className="mt-1 whitespace-pre-wrap text-foreground">
                {finding.recommendation}
              </p>
            </div>
          ) : null}
          {finding.rule_id || finding.confidence !== null ? (
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
              {finding.rule_id ? (
                <span>
                  Rule: <span className="font-mono">{finding.rule_id}</span>
                </span>
              ) : null}
              {finding.confidence !== null ? (
                <span>
                  Confidence:{' '}
                  <span className="tabular-nums">
                    {(finding.confidence * 100).toFixed(0)}%
                  </span>
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
