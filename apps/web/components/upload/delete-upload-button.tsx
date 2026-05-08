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
import { useDeleteUploadMutation } from '@/lib/api/uploads/use-upload';

type DeleteUploadButtonProps = {
  uploadId: string;
  /** Original filename of the upload — used for the SR-only aria-label. */
  uploadName: string;
};

/**
 * Row-level delete affordance on the `/uploads` index. Same dialog flow as
 * the scan-row delete button, with copy that warns about cascade deletion of
 * scans, findings, and the extracted files on disk. We do not surface a
 * scan-count in v1 — the upload list response doesn't include it (per
 * docs/API.md / `apps/api/app/schemas/upload.py`) and we are not changing
 * the API in this PR.
 */
export function DeleteUploadButton({
  uploadId,
  uploadName,
}: Readonly<DeleteUploadButtonProps>) {
  const [open, setOpen] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const mutation = useDeleteUploadMutation();

  const handleConfirm = () => {
    setErrorText(null);
    mutation.mutate(uploadId, {
      onError: (err) => {
        setErrorText(err.message || 'Could not delete this upload.');
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
              data-testid={`upload-row-${uploadId}-delete`}
              aria-label={`Delete ${uploadName}`}
              className="h-7 gap-1 px-2 text-xs"
              onClick={(event: React.MouseEvent<HTMLButtonElement>) => {
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
            <AlertDialogTitle>Delete upload permanently?</AlertDialogTitle>
            <AlertDialogDescription>
              This will also delete associated scans and findings, and remove
              the extracted files from disk. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              data-testid={`upload-row-${uploadId}-delete-cancel`}
              disabled={mutation.isPending}
            >
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              data-testid={`upload-row-${uploadId}-delete-confirm`}
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
          data-testid={`upload-row-${uploadId}-delete-error`}
          role="alert"
          className="px-1 text-xs text-red-600 dark:text-red-300"
        >
          {errorText}
        </p>
      ) : null}
    </>
  );
}
