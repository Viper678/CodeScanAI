'use client';

import { Loader2, Trash2 } from 'lucide-react';
import { useState, type MouseEvent, type ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type ConfirmDeleteButtonProps = {
  /** Aria-label on the idle trigger — also used as the confirm-state hint
   *  prefix ("Delete <label>?"). Keep it short ("scan", "upload"). */
  label: string;
  /** Async handler called when the user clicks Confirm. The component holds
   *  the spinner until the returned promise resolves or rejects. */
  onConfirm: () => Promise<void>;
  /** Opt-out of the icon — useful when the button sits in a header. */
  withIcon?: boolean;
  /** Show "Delete" + label as a wider button instead of an icon-only trigger. */
  variant?: 'icon' | 'wide';
  /** Whether the trigger is disabled (e.g. another mutation in flight). */
  disabled?: boolean;
  /** Optional handler invoked when the mutation rejects. */
  onError?: (error: unknown) => void;
  /** test-id stem; the component appends "-trigger" / "-confirm" / "-cancel". */
  testId?: string;
  /** Trailing className applied to the outer wrapper. */
  className?: string;
  /** Optional extra elements rendered inline after the wrapper — useful for
   *  a sibling error message in a row. */
  children?: ReactNode;
};

type State = 'idle' | 'confirming' | 'pending';

/**
 * Inline confirm-then-delete button. No modal — clicking the trigger flips
 * the control into a `Confirm | Cancel` pair, so destructive intent is
 * always two-step but never blocks the rest of the page.
 *
 * Why an inline confirmation rather than a modal? Three reasons:
 *
 * 1. Deletes happen in row context (scan list, upload list). A modal
 *    forces the user to recover their place after the click.
 * 2. We don't ship `radix-ui/alert-dialog` yet and adding it for one feature
 *    is dependency churn (per the docker-web-deps memory).
 * 3. The state machine is trivial and worth owning.
 *
 * State machine: idle → confirming → pending → idle (on success/error). The
 * confirming → idle transition is also reachable via the Cancel button.
 */
export function ConfirmDeleteButton({
  label,
  onConfirm,
  withIcon = true,
  variant = 'icon',
  disabled = false,
  onError,
  testId,
  className,
  children,
}: Readonly<ConfirmDeleteButtonProps>) {
  const [state, setState] = useState<State>('idle');

  const triggerTestId = testId ? `${testId}-trigger` : undefined;
  const confirmTestId = testId ? `${testId}-confirm` : undefined;
  const cancelTestId = testId ? `${testId}-cancel` : undefined;

  const handleTriggerClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (disabled || state !== 'idle') return;
    setState('confirming');
  };

  const handleConfirmClick = async (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setState('pending');
    try {
      await onConfirm();
      // Caller usually unmounts us on success (row removed / page navigated).
      // Fall back to idle in case we survive — keeps the button reusable.
      setState('idle');
    } catch (err) {
      onError?.(err);
      setState('idle');
    }
  };

  const handleCancelClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setState('idle');
  };

  if (state === 'idle') {
    if (variant === 'icon') {
      return (
        <span className={cn('inline-flex items-center', className)}>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={handleTriggerClick}
            disabled={disabled}
            aria-label={`Delete ${label}`}
            data-testid={triggerTestId}
            className="text-muted-foreground hover:text-red-500"
          >
            <Trash2 aria-hidden="true" />
          </Button>
          {children}
        </span>
      );
    }
    return (
      <span className={cn('inline-flex items-center gap-2', className)}>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          onClick={handleTriggerClick}
          disabled={disabled}
          aria-label={`Delete ${label}`}
          data-testid={triggerTestId}
          className="gap-1.5"
        >
          {withIcon ? <Trash2 aria-hidden="true" /> : null}
          Delete
        </Button>
        {children}
      </span>
    );
  }

  // Confirming or pending — render the same two-button pair so layout doesn't
  // jump when the spinner replaces the trash icon.
  const isPending = state === 'pending';
  return (
    <span
      className={cn('inline-flex items-center gap-1.5', className)}
      data-state={state}
      role="group"
      aria-label={`Confirm deleting ${label}`}
    >
      <Button
        type="button"
        variant="destructive"
        size="sm"
        onClick={handleConfirmClick}
        disabled={isPending}
        data-testid={confirmTestId}
        className="gap-1.5"
      >
        {isPending ? (
          <Loader2 className="animate-spin" aria-hidden="true" />
        ) : (
          <Trash2 aria-hidden="true" />
        )}
        {isPending ? 'Deleting…' : 'Confirm'}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={handleCancelClick}
        disabled={isPending}
        data-testid={cancelTestId}
      >
        Cancel
      </Button>
      {children}
    </span>
  );
}
