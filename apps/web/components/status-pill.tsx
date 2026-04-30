import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export type Status =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

const STATUS_STYLES: Record<Status, string> = {
  pending: 'border-zinc-500/30 bg-zinc-500/10 text-zinc-600 dark:text-zinc-300',
  running: 'border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-300',
  completed:
    'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300',
  failed: 'border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-300',
  cancelled:
    'border-orange-500/30 bg-orange-500/10 text-orange-600 dark:text-orange-300',
};

type StatusPillProps = {
  status: Status;
};

export function StatusPill({ status }: Readonly<StatusPillProps>) {
  return (
    <Badge
      variant="outline"
      className={cn(
        'rounded-full px-2.5 py-1 text-xs font-medium capitalize',
        STATUS_STYLES[status],
      )}
    >
      {status}
    </Badge>
  );
}
