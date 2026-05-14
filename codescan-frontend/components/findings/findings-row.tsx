'use client';

import Link from 'next/link';
import { ChevronRight } from 'lucide-react';
import { useId, type KeyboardEvent } from 'react';

import { SeverityDot } from '@/components/findings/severity-dot';
import { SnippetViewer } from '@/components/findings/snippet-viewer';
import type { Finding } from '@/lib/api/findings/types';
import { cn } from '@/lib/utils';

const SCAN_TYPE_LABEL = {
  bugs: 'Bugs',
  keywords: 'Keywords',
  security: 'Security',
} as const;

type FindingsRowProps = {
  finding: Finding;
  expanded: boolean;
  onToggle: () => void;
  /**
   * URL to the file viewer for this finding's file. Includes the originating
   * scan + line in the query string so the viewer can scope its sidebar +
   * scroll to the offending line. Optional during the codex deferred period
   * (T4.2 P2) — once T4.3 ships every caller passes it.
   */
  fileHref?: string | null;
};

/**
 * One row in the findings table.
 *
 * The whole row is keyboard-activatable (Enter / Space toggle expansion) and
 * carries `aria-expanded` + `aria-controls` so screen readers announce the
 * disclosure state. The file path renders as a `<Link>` to the file viewer
 * (T4.3) when `fileHref` is supplied; the link's click is `stopPropagation`'d
 * so navigating to the viewer doesn't also toggle the row.
 */
export function FindingsRow({
  finding,
  expanded,
  onToggle,
  fileHref,
}: Readonly<FindingsRowProps>) {
  const detailsId = useId();
  const lineLabel =
    finding.line_start === null
      ? '—'
      : finding.line_end && finding.line_end !== finding.line_start
        ? `${finding.line_start}–${finding.line_end}`
        : String(finding.line_start);

  const handleKeyDown = (event: KeyboardEvent<HTMLTableRowElement>) => {
    // Only toggle when the row itself is the focus target. Without this
    // guard, a focusable child (the file-viewer link added in T4.3) would
    // have its Enter / Space activations canceled by our preventDefault()
    // because the keydown bubbles up to this listener.
    if (event.target !== event.currentTarget) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onToggle();
    }
  };

  return (
    <>
      <tr
        data-testid={`finding-row-${finding.id}`}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={onToggle}
        onKeyDown={handleKeyDown}
        className={cn(
          'cursor-pointer border-b border-border/60 text-sm outline-none transition-colors hover:bg-muted/40 focus-visible:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring/40',
          expanded && 'bg-muted/30',
        )}
      >
        <td className="px-4 py-3 align-middle">
          <span className="flex items-center gap-2">
            <ChevronRight
              aria-hidden="true"
              className={cn(
                'size-4 shrink-0 text-muted-foreground transition-transform',
                expanded && 'rotate-90',
              )}
            />
            <SeverityDot severity={finding.severity} />
            <span className="sr-only">Severity: {finding.severity}</span>
          </span>
        </td>
        <td className="px-4 py-3 align-middle">
          {fileHref ? (
            <Link
              href={fileHref}
              // Stop click + key bubbling so navigating to the viewer doesn't
              // also toggle the row's expansion. The keyboard-target guard in
              // handleKeyDown stops Enter/Space from toggling, but onClick
              // bubbles up too — explicitly stop both.
              onClick={(event) => event.stopPropagation()}
              className="block truncate font-mono text-xs text-foreground underline-offset-2 hover:underline focus-visible:underline"
              title={finding.file.path}
            >
              {finding.file.path}
            </Link>
          ) : (
            <span
              className="block truncate font-mono text-xs text-foreground"
              title={finding.file.path}
            >
              {finding.file.path}
            </span>
          )}
        </td>
        <td className="px-4 py-3 align-middle font-mono text-xs tabular-nums text-muted-foreground">
          {lineLabel}
        </td>
        <td className="px-4 py-3 align-middle text-xs text-muted-foreground">
          {SCAN_TYPE_LABEL[finding.scan_type]}
        </td>
        <td className="px-4 py-3 align-middle">
          <span
            className="block truncate text-foreground"
            title={finding.title}
          >
            {finding.title}
          </span>
        </td>
      </tr>

      {expanded ? (
        <tr
          id={detailsId}
          data-testid={`finding-details-${finding.id}`}
          className="border-b border-border/60 bg-muted/10"
        >
          <td colSpan={5} className="px-12 py-4">
            <dl className="space-y-3 text-sm">
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Message
                </dt>
                <dd className="mt-1 whitespace-pre-wrap text-foreground">
                  {finding.message}
                </dd>
              </div>
              {finding.recommendation ? (
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Recommendation
                  </dt>
                  <dd className="mt-1 whitespace-pre-wrap text-foreground">
                    {finding.recommendation}
                  </dd>
                </div>
              ) : null}
              {finding.snippet ? (
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Snippet
                  </dt>
                  <dd className="mt-1">
                    <SnippetViewer
                      snippet={finding.snippet}
                      startLine={finding.line_start}
                      lineStart={finding.line_start}
                      lineEnd={finding.line_end}
                    />
                  </dd>
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
            </dl>
          </td>
        </tr>
      ) : null}
    </>
  );
}
