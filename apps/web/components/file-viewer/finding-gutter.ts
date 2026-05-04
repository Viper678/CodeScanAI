/**
 * CodeMirror 6 gutter that renders a severity-colored dot per file line
 * containing a finding.
 *
 * Implementation choice: ``gutter`` from ``@codemirror/view`` accepts a
 * ``lineMarker`` callback. We index the supplied findings by their line
 * once on construction so the per-line lookup stays O(1) — re-running
 * through the array on every visible line during scroll would jank a
 * 5k-line file.
 *
 * Click handling routes through the host React component: we expose an
 * ``onClickFinding(findingId)`` hook so the sidebar can mirror the
 * selection state. Doing the React-state mutation here would couple the
 * extension to the component lifecycle awkwardly — easier to bubble the
 * intent up via a callback the component supplies at construction time.
 */
import { gutter, GutterMarker } from '@codemirror/view';
import type { Extension } from '@codemirror/state';

import type { Severity } from '@/lib/api/scans/types';

/** Mirror of ``SeverityDot`` styling — kept in lockstep with Tailwind tokens. */
const SEVERITY_COLOR: Record<Severity, string> = {
  critical: 'var(--severity-critical, #dc2626)',
  high: 'var(--severity-high, #ea580c)',
  info: 'var(--severity-info, #6b7280)',
  low: 'var(--severity-low, #2563eb)',
  medium: 'var(--severity-medium, #d97706)',
};

export type FindingMarker = {
  id: string;
  line: number;
  severity: Severity;
};

class SeverityDotMarker extends GutterMarker {
  public constructor(
    private readonly findings: FindingMarker[],
    private readonly onClick: (findingId: string) => void,
  ) {
    super();
  }

  public override eq(other: GutterMarker): boolean {
    if (!(other instanceof SeverityDotMarker)) return false;
    if (other.findings.length !== this.findings.length) return false;
    // Cheap equality: compare ids in order. Findings list is small per line.
    return this.findings.every((f, i) => other.findings[i]?.id === f.id);
  }

  public override toDOM(): HTMLElement {
    const wrap = document.createElement('span');
    wrap.className = 'cs-finding-gutter-wrap';
    wrap.style.display = 'inline-flex';
    wrap.style.alignItems = 'center';
    wrap.style.gap = '2px';
    wrap.style.padding = '0 4px';
    wrap.style.cursor = 'pointer';
    // Highest-severity-first within a single line. Caller already sorts,
    // but be defensive — markers can come from React in any order.
    const sorted = [...this.findings].sort(
      (a, b) => severityRank(a.severity) - severityRank(b.severity),
    );
    for (const f of sorted) {
      const dot = document.createElement('span');
      dot.dataset.findingId = f.id;
      dot.dataset.severity = f.severity;
      dot.title = `Finding (${f.severity})`;
      dot.style.display = 'inline-block';
      dot.style.width = '6px';
      dot.style.height = '6px';
      dot.style.borderRadius = '50%';
      dot.style.background = SEVERITY_COLOR[f.severity];
      wrap.appendChild(dot);
    }
    // Single click handler on the wrapper — clicking any dot triggers the
    // first finding on that line. The sidebar handles the multi-finding
    // disambiguation if the user wants to pick a different one.
    wrap.addEventListener('click', (event) => {
      event.preventDefault();
      const first = sorted[0];
      if (first) this.onClick(first.id);
    });
    return wrap;
  }
}

function severityRank(severity: Severity): number {
  switch (severity) {
    case 'critical':
      return 0;
    case 'high':
      return 1;
    case 'medium':
      return 2;
    case 'low':
      return 3;
    case 'info':
      return 4;
  }
}

/**
 * Build a CodeMirror gutter extension keyed off the supplied findings
 * list. Re-call when findings change — the extension is immutable, so
 * the host should reconfigure (`EditorView.dispatch({ effects: ... })`)
 * or simply re-mount with a fresh `extensions` array on every change.
 * The viewer takes the latter approach because findings rarely churn
 * after initial load.
 */
export function findingGutter(
  findings: FindingMarker[],
  onClick: (findingId: string) => void,
): Extension {
  const byLine = new Map<number, FindingMarker[]>();
  for (const f of findings) {
    const bucket = byLine.get(f.line);
    if (bucket) {
      bucket.push(f);
    } else {
      byLine.set(f.line, [f]);
    }
  }
  return gutter({
    class: 'cs-finding-gutter',
    lineMarker(view, line) {
      // CodeMirror's `line.from` is a document offset; translate to a
      // 1-indexed line number to match the API contract.
      const lineNumber = view.state.doc.lineAt(line.from).number;
      const matches = byLine.get(lineNumber);
      if (!matches || matches.length === 0) return null;
      return new SeverityDotMarker(matches, onClick);
    },
    initialSpacer: () => new SeverityDotMarker([], () => undefined),
  });
}
