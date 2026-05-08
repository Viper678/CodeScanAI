'use client';

import { Loader2, Trash2 } from 'lucide-react';
import { useState } from 'react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { useDeleteScanMutation } from '@/lib/api/scans/use-scans';

type DeleteScanButtonProps = {
  scanId: string;
  /** Visible only to screen readers — gives the icon button a friendly label. */
  scanName: string;
};

/**
 * Row-level delete affordance on the `/scans` index. Opens a confirmation
 * dialog (Esc / Cancel dismiss; Enter on the destructive button confirms),
 * then calls `DELETE /scans/{id}` and lets the listing's TanStack key
 * invalidate so the row drops out on the next render.
 *
 * Errors surface as inline red text under the trigger — same pattern the
 * sibling re-run button uses, since this codebase doesn't have a toast
 * library yet.
 */
export function DeleteScanButton({
  scanId,
  scanName,
}: Readonly<DeleteScanButtonProps>) {
  const [open, setOpen] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const mutation = useDeleteScanMutation();

  const handleConfirm = () => {
    // The action button is a plain <button> (not a base-ui Close) — see the
    // AlertDialogAction docstring — so the dialog stays open while the
    // mutation runs. We close it ourselves on success.
    setErrorText(null);
    mutation.mutate(scanId, {
      onError: (err) => {
        setErrorText(err.message || 'Could not delete this scan.');
      },
      onSuccess: () => {
        setOpen(false);
      },
    });
  };

  return (
    <>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogTrigger
          render={
            <Button
              type="button"
              variant="destructive"
              size="sm"
              data-testid={`scan-row-${scanId}-delete`}
              aria-label={`Delete ${scanName}`}
              className="h-7 gap-1 px-2 text-xs"
              onClick={(event: React.MouseEvent<HTMLButtonElement>) => {
                // Keep the row's underlying anchor from navigating to the
                // scan detail page when the user clicks Delete on a row.
                // Mirrors the re-run button's preventDefault/stopPropagation
                // pair on the same row.
                event.preventDefault();
                event.stopPropagation();
              }}
            >
              <Trash2 className="size-3" aria-hidden="true" />
              Delete
            </Button>
          }
        />
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete scan permanently?</AlertDialogTitle>
            <AlertDialogDescription>
              All findings for this scan will be removed. This action cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              data-testid={`scan-row-${scanId}-delete-cancel`}
              disabled={mutation.isPending}
            >
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              data-testid={`scan-row-${scanId}-delete-confirm`}
              disabled={mutation.isPending}
              onClick={handleConfirm}
            >
              {mutation.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              ) : null}
              {mutation.isPending ? 'Deleting…' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {errorText ? (
        <p
          data-testid={`scan-row-${scanId}-delete-error`}
          role="alert"
          className="px-1 text-xs text-red-600 dark:text-red-300"
        >
          {errorText}
        </p>
      ) : null}
    </>
  );
}
