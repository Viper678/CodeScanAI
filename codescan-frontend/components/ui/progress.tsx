'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

type ProgressProps = React.ComponentProps<'div'> & {
  /** 0..100. `null` renders an indeterminate animated bar. */
  value: number | null;
};

/**
 * Minimal progress bar. Avoids pulling in radix just for this — the underlying
 * markup matches the ARIA pattern (`role="progressbar"` + value-now).
 */
function Progress({ className, value, ...props }: ProgressProps) {
  const isIndeterminate = value === null;
  const clamped = isIndeterminate ? 0 : Math.min(100, Math.max(0, value));

  return (
    <div
      data-slot="progress"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={isIndeterminate ? undefined : Math.round(clamped)}
      className={cn(
        'relative h-2 w-full overflow-hidden rounded-full bg-muted',
        className,
      )}
      {...props}
    >
      <div
        data-slot="progress-indicator"
        className={cn(
          'h-full rounded-full bg-primary transition-[width] duration-150 ease-out',
          isIndeterminate && 'w-1/3 animate-pulse',
        )}
        style={isIndeterminate ? undefined : { width: `${clamped}%` }}
      />
    </div>
  );
}

export { Progress };
