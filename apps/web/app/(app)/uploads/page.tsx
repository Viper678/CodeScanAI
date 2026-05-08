'use client';

import Link from 'next/link';
import {
  AlertTriangle,
  FileArchive,
  FileUp,
  Loader2,
  Plus,
} from 'lucide-react';

import { EmptyState } from '@/components/empty-state';
import { StatusPill } from '@/components/status-pill';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useUploadsQuery } from '@/lib/api/uploads/use-upload';
import type { UploadDetail } from '@/lib/api/uploads/types';
import { formatBytes, formatShortDate } from '@/lib/format';
import { cn } from '@/lib/utils';

const PAGE_LIMIT = 20;

export default function UploadsPage() {
  const query = useUploadsQuery({ limit: PAGE_LIMIT });

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight">Uploads</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Archives and loose-file batches you&apos;ve sent to CodeScan. Click
            a row to inspect its file tree.
          </p>
        </div>
        <Link
          href="/uploads/new"
          className={cn(
            buttonVariants({ size: 'lg' }),
            'bg-primary text-primary-foreground hover:bg-primary/90',
          )}
        >
          <Plus className="size-4" aria-hidden="true" />
          Start a new scan
        </Link>
      </div>

      {query.isPending ? (
        <ListSkeleton label="Loading uploads…" />
      ) : query.error ? (
        <ErrorPanel
          message={query.error.message}
          onRetry={() => {
            void query.refetch();
          }}
        />
      ) : query.data.items.length === 0 ? (
        <EmptyState
          icon={FileUp}
          title="No uploads yet"
          description="Bring in a repository archive or a small file set to seed the scan wizard and file tree."
          action={{
            href: '/uploads/new',
            label: 'Upload your first repo',
          }}
        />
      ) : (
        <UploadsList items={query.data.items} total={query.data.total} />
      )}
    </div>
  );
}

type UploadsListProps = {
  items: UploadDetail[];
  total: number;
};

function UploadsList({ items, total }: Readonly<UploadsListProps>) {
  return (
    <div className="space-y-3">
      <ul className="space-y-2" data-testid="uploads-list">
        {items.map((upload) => (
          <li key={upload.id}>
            <UploadRow upload={upload} />
          </li>
        ))}
      </ul>
      {total > items.length ? (
        <p className="text-xs text-muted-foreground">
          Showing first {items.length} of {total} — pagination lands later.
        </p>
      ) : null}
    </div>
  );
}

type UploadRowProps = {
  upload: UploadDetail;
};

function UploadRow({ upload }: Readonly<UploadRowProps>) {
  const fileCountText =
    upload.status === 'ready' && upload.file_count !== null
      ? `${upload.file_count} files`
      : '—';

  return (
    <Link
      href={`/uploads/${upload.id}/tree-preview`}
      data-testid={`upload-row-${upload.id}`}
      className={cn(
        'flex items-center justify-between gap-4 rounded-2xl border border-border/80 bg-card/60 px-4 py-3',
        'transition-colors hover:border-border hover:bg-card focus-visible:outline-none',
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
      )}
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <FileArchive className="size-4" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <p
            className="truncate text-sm font-medium text-foreground"
            title={upload.original_name}
          >
            {upload.original_name}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            kind={upload.kind} · {formatBytes(upload.size_bytes)} ·{' '}
            {fileCountText}
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <StatusPill status={upload.status} />
        <span className="hidden whitespace-nowrap text-xs text-muted-foreground md:inline">
          {formatShortDate(upload.created_at)}
        </span>
      </div>
    </Link>
  );
}

function ListSkeleton({ label }: Readonly<{ label: string }>) {
  return (
    <div className="flex items-center gap-3 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

type ErrorPanelProps = {
  message: string;
  onRetry: () => void;
};

function ErrorPanel({ message, onRetry }: Readonly<ErrorPanelProps>) {
  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          <AlertTriangle
            className="size-4 text-muted-foreground"
            aria-hidden="true"
          />
          Could not load uploads.
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{message}</p>
        <div className="flex justify-end">
          <Button variant="outline" onClick={onRetry}>
            Retry
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
