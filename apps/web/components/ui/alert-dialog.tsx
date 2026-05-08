'use client';

import * as React from 'react';
import { AlertDialog as AlertDialogPrimitive } from '@base-ui/react/alert-dialog';

import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * Headless alert-dialog primitive group, modeled on shadcn's AlertDialog API
 * but built on `@base-ui/react/alert-dialog` (already in package.json — see
 * `components/ui/dropdown-menu.tsx` for the same pattern).
 *
 * Esc dismisses, focus is trapped while open, and focus is restored to the
 * trigger on close — all from the underlying primitive. Callers wire the
 * destructive action via the `<AlertDialogAction>` button slot.
 */

function AlertDialog(
  props: AlertDialogPrimitive.Root.Props,
): React.JSX.Element {
  return <AlertDialogPrimitive.Root {...props} />;
}

function AlertDialogTrigger(
  props: AlertDialogPrimitive.Trigger.Props,
): React.JSX.Element {
  return (
    <AlertDialogPrimitive.Trigger data-slot="alert-dialog-trigger" {...props} />
  );
}

function AlertDialogPortal(
  props: AlertDialogPrimitive.Portal.Props,
): React.JSX.Element {
  return (
    <AlertDialogPrimitive.Portal data-slot="alert-dialog-portal" {...props} />
  );
}

function AlertDialogBackdrop({
  className,
  ...props
}: AlertDialogPrimitive.Backdrop.Props): React.JSX.Element {
  return (
    <AlertDialogPrimitive.Backdrop
      data-slot="alert-dialog-backdrop"
      className={cn(
        'fixed inset-0 z-50 bg-black/60 backdrop-blur-sm data-open:animate-in data-open:fade-in-0 data-closed:animate-out data-closed:fade-out-0',
        className,
      )}
      {...props}
    />
  );
}

function AlertDialogContent({
  className,
  ...props
}: AlertDialogPrimitive.Popup.Props): React.JSX.Element {
  return (
    <AlertDialogPortal>
      <AlertDialogBackdrop />
      <AlertDialogPrimitive.Popup
        data-slot="alert-dialog-content"
        className={cn(
          'fixed left-1/2 top-1/2 z-50 grid w-full max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 rounded-2xl border border-border/80 bg-background p-6 shadow-lg outline-none ring-1 ring-foreground/10 duration-150',
          'data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95',
          'data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95',
          className,
        )}
        {...props}
      />
    </AlertDialogPortal>
  );
}

function AlertDialogHeader({
  className,
  ...props
}: React.ComponentProps<'div'>): React.JSX.Element {
  return (
    <div
      data-slot="alert-dialog-header"
      className={cn('flex flex-col gap-2 text-center sm:text-left', className)}
      {...props}
    />
  );
}

function AlertDialogFooter({
  className,
  ...props
}: React.ComponentProps<'div'>): React.JSX.Element {
  return (
    <div
      data-slot="alert-dialog-footer"
      className={cn(
        'flex flex-col-reverse gap-2 sm:flex-row sm:justify-end',
        className,
      )}
      {...props}
    />
  );
}

function AlertDialogTitle({
  className,
  ...props
}: AlertDialogPrimitive.Title.Props): React.JSX.Element {
  return (
    <AlertDialogPrimitive.Title
      data-slot="alert-dialog-title"
      className={cn('text-lg font-semibold tracking-tight', className)}
      {...props}
    />
  );
}

function AlertDialogDescription({
  className,
  ...props
}: AlertDialogPrimitive.Description.Props): React.JSX.Element {
  return (
    <AlertDialogPrimitive.Description
      data-slot="alert-dialog-description"
      className={cn('text-sm text-muted-foreground', className)}
      {...props}
    />
  );
}

/**
 * Confirm slot. Renders as a plain `<button>` (NOT a base-ui `Close`) so the
 * caller can keep the dialog open during an async confirm — typical pattern
 * for destructive actions where we want to surface a spinner and stay open
 * if the network call fails. The caller is responsible for closing the
 * dialog on success (`onOpenChange={setOpen}` + `setOpen(false)` in the
 * mutation's `onSuccess`).
 *
 * Defaults to the `destructive` variant since the only place this primitive
 * is used in v1 is permanent-delete dialogs. Pass `className` to override.
 */
function AlertDialogAction({
  className,
  ...props
}: React.ComponentProps<'button'>): React.JSX.Element {
  return (
    <button
      type="button"
      data-slot="alert-dialog-action"
      className={cn(buttonVariants({ variant: 'destructive' }), className)}
      {...props}
    />
  );
}

/** Cancel slot — neutral outline, autofocused per WAI-ARIA APG guidance. */
function AlertDialogCancel({
  className,
  ...props
}: AlertDialogPrimitive.Close.Props): React.JSX.Element {
  return (
    <AlertDialogPrimitive.Close
      data-slot="alert-dialog-cancel"
      className={cn(buttonVariants({ variant: 'outline' }), className)}
      {...props}
    />
  );
}

export {
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogPortal,
  AlertDialogBackdrop,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogAction,
  AlertDialogCancel,
};
