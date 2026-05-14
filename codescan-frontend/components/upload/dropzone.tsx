'use client';

import { useCallback, useId, useRef, useState, type DragEvent } from 'react';
import { UploadCloud } from 'lucide-react';

import { cn } from '@/lib/utils';

type DropzoneProps = {
  /** Accept attribute for the hidden input. Defaults to `.zip`. */
  accept?: string;
  /** Disable interaction (e.g. while uploading or extracting). */
  disabled?: boolean;
  /** Called when the user picks a file via drop or browse. */
  onFileSelected: (file: File) => void;
};

/**
 * Drag-and-drop or click-to-browse file picker.
 *
 * Pure controlled UI — it never holds the selected file in state. The parent
 * is responsible for what to do with it (start an upload, validate, etc.).
 */
export function Dropzone({
  accept = '.zip',
  disabled = false,
  onFileSelected,
}: Readonly<DropzoneProps>) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const inputId = useId();
  const [isDragging, setIsDragging] = useState(false);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      const file = files[0];
      if (!file) return;
      onFileSelected(file);
    },
    [onFileSelected],
  );

  const onDrop = useCallback(
    (event: DragEvent<HTMLLabelElement>) => {
      event.preventDefault();
      setIsDragging(false);
      if (disabled) return;
      handleFiles(event.dataTransfer?.files ?? null);
    },
    [disabled, handleFiles],
  );

  const onDragOver = useCallback(
    (event: DragEvent<HTMLLabelElement>) => {
      event.preventDefault();
      if (disabled) return;
      setIsDragging(true);
    },
    [disabled],
  );

  const onDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  return (
    <label
      htmlFor={inputId}
      data-testid="upload-dropzone"
      data-disabled={disabled || undefined}
      data-dragging={isDragging || undefined}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      className={cn(
        'group/dropzone flex min-h-72 cursor-pointer flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed border-border/80 bg-muted/15 px-6 py-12 text-center transition-colors',
        'hover:border-primary/60 hover:bg-primary/5',
        'focus-within:border-primary focus-within:bg-primary/5',
        isDragging && 'border-primary bg-primary/10',
        disabled &&
          'pointer-events-none cursor-not-allowed opacity-60 hover:border-border/80 hover:bg-muted/15',
      )}
    >
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={accept}
        disabled={disabled}
        onChange={(event) => handleFiles(event.currentTarget.files)}
        className="sr-only"
      />
      <span
        aria-hidden="true"
        className="flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary"
      >
        <UploadCloud className="size-7" />
      </span>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">
          Drop a <code className="font-mono text-xs">.zip</code> here, or click
          to browse
        </p>
        <p className="text-xs text-muted-foreground">
          Limits: 100 MB per archive · 50 MB per loose file · up to 50 loose
          files per upload
        </p>
      </div>
    </label>
  );
}
