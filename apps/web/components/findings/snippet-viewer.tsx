import { cn } from '@/lib/utils';

type SnippetViewerProps = {
  snippet: string;
  /** First *file* line number for the snippet's first line (1-indexed). */
  startLine: number | null;
  /** Last file line covered by the finding (inclusive); used for highlight band. */
  lineEnd: number | null;
  /** The single line where the finding begins (inclusive lower bound). */
  lineStart: number | null;
};

/**
 * Render a code snippet with line numbers and highlight the offending range.
 *
 * The snippet may include leading context lines, so the rendered gutter
 * begins at `startLine` (defaulting to `lineStart` and finally to 1 if both
 * are missing). Lines whose computed file-line number falls within
 * `[lineStart, lineEnd]` get the highlight band.
 *
 * Intentionally lightweight — full syntax highlighting + virtualization land
 * in T4.3 (file viewer). For the row-expansion preview, plain monospace +
 * highlight is sufficient and avoids dragging CodeMirror into the bundle for
 * a 5-line preview.
 */
export function SnippetViewer({
  snippet,
  startLine,
  lineEnd,
  lineStart,
}: Readonly<SnippetViewerProps>) {
  const lines = snippet.replace(/\n$/, '').split('\n');
  const baseLine = startLine ?? lineStart ?? 1;
  const highlightLow = lineStart ?? baseLine;
  const highlightHigh = lineEnd ?? highlightLow;
  const gutterWidth = String(baseLine + lines.length - 1).length;

  return (
    <pre
      data-testid="snippet-viewer"
      className="overflow-x-auto rounded-md border border-border/60 bg-muted/40 p-0 font-mono text-xs leading-relaxed"
    >
      <code className="block">
        {lines.map((line, index) => {
          const lineNumber = baseLine + index;
          const isHighlighted =
            lineNumber >= highlightLow && lineNumber <= highlightHigh;
          return (
            <span
              key={`${lineNumber}-${index}`}
              data-testid={`snippet-line-${lineNumber}`}
              data-highlighted={isHighlighted ? 'true' : 'false'}
              className={cn(
                'flex w-full items-stretch',
                isHighlighted && 'bg-severity-high/10',
              )}
            >
              <span
                aria-hidden="true"
                className="select-none border-r border-border/60 px-3 py-0.5 text-right tabular-nums text-muted-foreground"
                style={{ minWidth: `${gutterWidth + 2}ch` }}
              >
                {lineNumber}
              </span>
              <span className="flex-1 whitespace-pre px-3 py-0.5 text-foreground">
                {line.length > 0 ? line : ' '}
              </span>
            </span>
          );
        })}
      </code>
    </pre>
  );
}
