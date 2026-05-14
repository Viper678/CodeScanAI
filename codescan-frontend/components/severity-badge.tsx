import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

const SEVERITY_STYLES: Record<Severity, string> = {
  critical:
    'border-severity-critical/30 bg-severity-critical/10 text-severity-critical',
  high: 'border-severity-high/30 bg-severity-high/10 text-severity-high',
  medium:
    'border-severity-medium/30 bg-severity-medium/10 text-amber-500 dark:text-severity-medium',
  low: 'border-severity-low/30 bg-severity-low/10 text-severity-low',
  info: 'border-severity-info/30 bg-severity-info/10 text-severity-info',
};

type SeverityBadgeProps = {
  severity: Severity;
};

export function SeverityBadge({ severity }: Readonly<SeverityBadgeProps>) {
  return (
    <Badge
      variant="outline"
      className={cn(
        'rounded-full px-2.5 py-1 text-xs font-medium capitalize',
        SEVERITY_STYLES[severity],
      )}
    >
      {severity}
    </Badge>
  );
}
