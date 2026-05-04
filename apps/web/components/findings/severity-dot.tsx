import { cn } from '@/lib/utils';
import type { Severity } from '@/lib/api/scans/types';

const SEVERITY_DOT_STYLES: Record<Severity, string> = {
  critical: 'bg-severity-critical',
  high: 'bg-severity-high',
  medium: 'bg-severity-medium',
  low: 'bg-severity-low',
  info: 'bg-severity-info',
};

type SeverityDotProps = {
  severity: Severity;
  className?: string;
};

/**
 * Tiny round colored marker for the findings table severity column. Pulls the
 * same Tailwind tokens defined in tailwind.config.ts so the dot, the
 * SeverityBadge, and the SeverityCounters all stay visually in lockstep.
 *
 * Renders as an aria-hidden span — the parent row supplies the textual
 * severity label for screen readers.
 */
export function SeverityDot({
  severity,
  className,
}: Readonly<SeverityDotProps>) {
  return (
    <span
      data-testid={`severity-dot-${severity}`}
      data-severity={severity}
      aria-hidden="true"
      className={cn(
        'inline-block size-2.5 shrink-0 rounded-full',
        SEVERITY_DOT_STYLES[severity],
        className,
      )}
    />
  );
}
