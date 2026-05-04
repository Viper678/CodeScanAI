'use client';

import { ChevronRight } from 'lucide-react';
import Link from 'next/link';
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
  /** `/uploads/{upload_id}/files/{file_id}` — link target landing in T4.3. */
  fileHref: string;
};

/**
 * One row in the findings table.
 *
 * The whole row is keyboard-activatable (Enter / Space toggle expansion) and
 * carries `aria-expanded` + `aria-controls` so screen readers announce the
 * disclosure state. The file path renders as a real `<Link>` inside the row;
 * we stop propagation on its click so following the link doesn't also toggle
 * the row open.
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

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onToggle();
    }
  };

  return (
    <div data-testid={`finding-row-${finding.id}`} className="contents">
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={onToggle}
        onKeyDown={handleKeyDown}
        className={cn(
          'grid cursor-pointer grid-cols-[auto_minmax(0,2fr)_minmax(0,4ch)_minmax(0,90px)_minmax(0,3fr)] items-center gap-3 border-b border-border/60 px-4 py-3 text-sm outline-none transition-colors hover:bg-muted/40 focus-visible:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring/40',
          expanded && 'bg-muted/30',
        )}
      >
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
        <Link
          href={fileHref}
          onClick={(event) => event.stopPropagation()}
          className="truncate font-mono text-xs text-foreground underline-offset-2 hover:underline"
          title={finding.file.path}
        >
          {finding.file.path}
        </Link>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {lineLabel}
        </span>
        <span className="text-xs text-muted-foreground">
          {SCAN_TYPE_LABEL[finding.scan_type]}
        </span>
        <span className="truncate text-foreground" title={finding.title}>
          {finding.title}
        </span>
      </div>

      {expanded ? (
        <div
          id={detailsId}
          data-testid={`finding-details-${finding.id}`}
          className="border-b border-border/60 bg-muted/10 px-12 py-4"
        >
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
        </div>
      ) : null}
    </div>
  );
}
