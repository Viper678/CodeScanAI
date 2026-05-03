'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, FileArchive, Loader2, X } from 'lucide-react';

import { ApiError } from '@/lib/api/client';
import {
  useUploadMutation,
  useUploadPolling,
} from '@/lib/api/uploads/use-upload';
import type { Upload } from '@/lib/api/uploads/types';
import { Dropzone } from '@/components/upload/dropzone';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { StatusPill } from '@/components/status-pill';
import { cn } from '@/lib/utils';

type UploadStepProps = {
  /** Fires once the upload row reaches `status='ready'`. */
  onReady: (upload: Upload) => void;
};

type Phase = 'idle' | 'uploading' | 'extracting' | 'failed';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

/** Step 1 of the upload wizard. */
export function UploadStep({ onReady }: Readonly<UploadStepProps>) {
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [progress, setProgress] = useState<number | null>(0);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const mutation = useUploadMutation();

  // Always abort any in-flight upload when this component unmounts (the user
  // navigates away mid-upload). The polling hook handles its own cancellation
  // via TanStack Query.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setFile(null);
    setPhase('idle');
    setProgress(0);
    setUploadId(null);
    setErrorMessage(null);
    mutation.reset();
  }, [mutation]);

  const startUpload = useCallback(
    (selected: File) => {
      // Brand-new upload: kill any previous controller first.
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setFile(selected);
      setErrorMessage(null);
      setProgress(0);
      setUploadId(null);
      setPhase('uploading');

      mutation.mutate(
        {
          file: selected,
          kind: 'zip',
          onProgress: (fraction) =>
            setProgress(fraction === null ? null : Math.round(fraction * 100)),
          signal: controller.signal,
        },
        {
          onError: (error) => {
            if (error instanceof DOMException && error.name === 'AbortError') {
              // User-initiated cancel: don't surface as failure.
              return;
            }
            const message =
              error instanceof ApiError
                ? error.message
                : 'Upload failed. Try again.';
            setPhase('failed');
            setErrorMessage(message);
          },
          onSuccess: (response) => {
            setProgress(100);
            setUploadId(response.id);
            setPhase('extracting');
          },
        },
      );
    },
    [mutation],
  );

  const handleReady = useCallback(
    (upload: Upload) => {
      onReady(upload);
    },
    [onReady],
  );

  const handleFailed = useCallback((upload: Upload) => {
    setPhase('failed');
    setErrorMessage(
      upload.error ??
        'Upload failed during extraction. Check the archive and try again.',
    );
  }, []);

  useUploadPolling(uploadId, {
    enabled: phase === 'extracting',
    onFailed: handleFailed,
    onReady: handleReady,
  });

  const dropzoneDisabled = phase === 'uploading' || phase === 'extracting';

  const statusPillStatus = useMemo(() => {
    switch (phase) {
      case 'uploading':
        return 'running' as const;
      case 'extracting':
        return 'running' as const;
      case 'failed':
        return 'failed' as const;
      default:
        return 'pending' as const;
    }
  }, [phase]);

  const statusLabel = useMemo(() => {
    switch (phase) {
      case 'uploading':
        return progress === null ? 'Uploading…' : `Uploading… ${progress}%`;
      case 'extracting':
        return 'Extracting…';
      case 'failed':
        return 'Failed';
      default:
        return 'Ready to upload';
    }
  }, [phase, progress]);

  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="text-base font-medium">Step 1 — Upload</CardTitle>
        <CardDescription>
          Drop a zip archive of the repo you want to scan. Extraction starts
          automatically once the upload completes.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <Dropzone
          accept=".zip,application/zip"
          disabled={dropzoneDisabled}
          onFileSelected={startUpload}
        />

        {file ? (
          <div
            data-testid="upload-detail"
            className="space-y-4 rounded-2xl border border-border/80 bg-card/60 p-4"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex min-w-0 items-start gap-3">
                <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <FileArchive className="size-4" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p
                    className="truncate text-sm font-medium text-foreground"
                    title={file.name}
                  >
                    {file.name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatBytes(file.size)}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <StatusPill status={statusPillStatus} />
                {phase === 'uploading' || phase === 'extracting' ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={reset}
                  >
                    <X className="size-3.5" aria-hidden="true" />
                    Cancel
                  </Button>
                ) : null}
              </div>
            </div>

            {phase === 'uploading' ? (
              <div className="space-y-2">
                <Progress value={progress} />
                <p className="text-xs text-muted-foreground">{statusLabel}</p>
              </div>
            ) : null}

            {phase === 'extracting' ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                <span>Extracting and indexing files…</span>
              </div>
            ) : null}

            {phase === 'failed' ? (
              <div
                role="alert"
                className={cn(
                  'flex items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3',
                  'text-red-600 dark:text-red-300',
                )}
              >
                <AlertTriangle
                  className="mt-0.5 size-4 shrink-0"
                  aria-hidden="true"
                />
                <div className="flex min-w-0 flex-1 flex-col gap-2">
                  <p className="text-sm font-medium">
                    {errorMessage ?? 'Upload failed.'}
                  </p>
                  <div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={reset}
                    >
                      Try again
                    </Button>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
