import { Check } from 'lucide-react';

import { cn } from '@/lib/utils';

type StepperProps = {
  currentStep: number;
  steps: string[];
};

export function Stepper({ currentStep, steps }: Readonly<StepperProps>) {
  return (
    <ol className="grid gap-3 md:grid-cols-4" aria-label="Scan setup progress">
      {steps.map((step, index) => {
        const state =
          index < currentStep
            ? 'completed'
            : index === currentStep
              ? 'active'
              : 'upcoming';

        return (
          <li key={step} className="relative">
            <div
              data-state={state}
              className={cn(
                'flex items-start gap-3 rounded-2xl border px-4 py-4 transition-colors',
                state === 'active' &&
                  'border-primary bg-primary/10 shadow-sm shadow-primary/10',
                state === 'completed' &&
                  'border-primary/40 bg-primary/5 text-foreground',
                state === 'upcoming' &&
                  'border-border/80 bg-card text-muted-foreground',
              )}
            >
              <span
                className={cn(
                  'mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold',
                  state === 'active' &&
                    'border-primary bg-primary text-primary-foreground',
                  state === 'completed' &&
                    'border-primary/40 bg-primary/10 text-primary',
                  state === 'upcoming' &&
                    'border-border bg-muted text-muted-foreground',
                )}
                aria-hidden="true"
              >
                {state === 'completed' ? (
                  <Check className="size-4" />
                ) : (
                  index + 1
                )}
              </span>
              <div>
                <p className="text-xs font-medium uppercase tracking-[0.2em] text-muted-foreground">
                  Step {index + 1}
                </p>
                <p className="mt-1 text-sm font-medium text-foreground">
                  {step}
                </p>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
