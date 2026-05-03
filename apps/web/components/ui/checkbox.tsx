'use client';

import * as React from 'react';
import { Check } from 'lucide-react';

import { cn } from '@/lib/utils';

type CheckboxProps = {
  checked: boolean;
  onCheckedChange: (next: boolean) => void;
  disabled?: boolean;
  id?: string;
  'aria-labelledby'?: string;
  'aria-describedby'?: string;
  'aria-invalid'?: React.AriaAttributes['aria-invalid'];
  className?: string;
};

/**
 * Minimal accessible checkbox built on top of `<button role="checkbox">`. We
 * don't yet have a shadcn Checkbox primitive in this repo and the scope of
 * T3.5 doesn't justify pulling one in — this matches the styling language of
 * `<Input>` and `<Button>` (rounded, ring on focus) and supports controlled
 * state only.
 */
export function Checkbox({
  checked,
  onCheckedChange,
  disabled,
  id,
  className,
  ...aria
}: Readonly<CheckboxProps>) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      data-state={checked ? 'checked' : 'unchecked'}
      data-slot="checkbox"
      disabled={disabled}
      id={id}
      onClick={() => {
        if (!disabled) onCheckedChange(!checked);
      }}
      className={cn(
        'inline-flex size-4 shrink-0 items-center justify-center rounded-[4px] border border-input bg-transparent text-primary-foreground transition-colors outline-none',
        'focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50',
        'disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50',
        'data-[state=checked]:border-primary data-[state=checked]:bg-primary',
        className,
      )}
      {...aria}
    >
      {checked ? <Check className="size-3" aria-hidden="true" /> : null}
    </button>
  );
}
