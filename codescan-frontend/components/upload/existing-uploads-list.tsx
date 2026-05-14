'use client';

import { AlertTriangle, FileArchive, FolderUp, Loader2 } from 'lucide-react';

import { ApiError } from '@/lib/api/client';
import { useUploadsQuery } from '@/lib/api/uploads/use-upload';
import type { Upload } from '@/lib/api/uploads/types';
import { Button } from '@/components/ui/button';
import { formatBytes } from '@/lib/format';
import { cn } from '@/lib/utils';

type ExistingUploadsListProps = {
  /** Fires when the user clicks "Use" on a ready upload. Same callback the
   *  fresh-upload path uses — keeps the wizard parent agnostic to which
   *  branch produced the upload. */
  onSelect: (upload: Upload) => void;
};

/** Step 1 alternative: pick a previously-uploaded archive instead of
 *  uploading a new one. The backend has always supported N scans per
 *  upload (``POST /scans`` takes any owned ``upload_id``); this list is
 *  the UI affordance for that re-use. Only ``status === 'ready'`` rows
 *  are selectable — extracting / failed / received rows render disabled
 *  so the user has a complete picture of their inventory.
 */
export function ExistingUploadsList({
  onSelect,
}: Readonly<ExistingUploadsListProps>) {
  // Server-side filter to ``status === 'ready'`` (Codex P2 follow-up). The
  // backend returns uploads newest-first, so a client-side filter against
  // the first 50 rows would mis-render the empty state if the latest 50
  // were all extracting/failed but an older ready upload existed.
  // ``limit: 100`` matches the api's hard cap and covers any realistic
  // ready-upload backlog at this iteration; true pagination (load more,
  // cursors) is a follow-up once the underlying ``useUploadsQuery`` hook
  // gains paging.
  const query = useUploadsQuery({ limit: 100, status: 'ready' });

  const ready: Upload[] = query.data?.items ?? [];

  if (query.isPending) {
    return (
      <div
        className="flex items-center gap-2 rounded-2xl border border-border/80 bg-card/60 p-4 text-sm text-muted-foreground"
        data-testid="existing-uploads-loading"
      >
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        <span>Loading your uploads…</span>
      </div>
    );
  }

  if (query.isError) {
    const message =
      query.error instanceof ApiError
        ? query.error.message
        : 'Could not load uploads.';
    return (
      <div
        role="alert"
        data-testid="existing-uploads-error"
        className={cn(
          'flex items-start gap-3 rounded-2xl border border-red-500/30 bg-red-500/10 p-4',
          'text-red-600 dark:text-red-300',
        )}
      >
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <p className="text-sm font-medium">{message}</p>
      </div>
    );
  }

  if (ready.length === 0) {
    return (
      <div
        data-testid="existing-uploads-empty"
        className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border/80 bg-card/40 p-6 text-center"
      >
        <FolderUp className="size-8 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          No ready uploads to choose from. Switch to{' '}
          <span className="font-medium text-foreground">Upload new</span> to
          send an archive — once extraction finishes it&apos;ll appear here for
          re-use.
        </p>
      </div>
    );
  }

  return (
    <ul
      data-testid="existing-uploads-list"
      className="divide-y divide-border/60 rounded-2xl border border-border/80 bg-card/60"
    >
      {ready.map((upload) => (
        <li
          key={upload.id}
          data-testid={`existing-upload-${upload.id}`}
          className="flex items-center gap-4 p-4"
        >
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <FileArchive className="size-4" aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <p
              className="truncate text-sm font-medium text-foreground"
              title={upload.original_name}
            >
              {upload.original_name}
            </p>
            <p className="text-xs text-muted-foreground">
              {formatBytes(upload.size_bytes)}
              {upload.scannable_count !== null
                ? ` · ${upload.scannable_count} scannable file${upload.scannable_count === 1 ? '' : 's'}`
                : ''}
              {' · '}
              {formatRelative(upload.created_at)}
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            onClick={() => onSelect(upload)}
            data-testid={`existing-upload-use-${upload.id}`}
          >
            Use
          </Button>
        </li>
      ))}
    </ul>
  );
}

/** Format an ISO timestamp into a short relative string ("2 hours ago",
 *  "yesterday", "May 13"). Falls back to the raw date for >30 days. */
function formatRelative(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return iso;
  const seconds = Math.floor((Date.now() - then.getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    return `${m} minute${m === 1 ? '' : 's'} ago`;
  }
  if (seconds < 86400) {
    const h = Math.floor(seconds / 3600);
    return `${h} hour${h === 1 ? '' : 's'} ago`;
  }
  const days = Math.floor(seconds / 86400);
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
