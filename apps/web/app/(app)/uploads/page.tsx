import Link from 'next/link';
import { FileUp, Plus } from 'lucide-react';

import { EmptyState } from '@/components/empty-state';
import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export default function UploadsPage() {
  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight">Uploads</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Uploaded archives and loose-file batches will appear here once T2.x
            lands.
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

      <EmptyState
        icon={FileUp}
        title="No uploads yet"
        description="Bring in a repository archive or a small file set to seed the scan wizard and file tree."
        action={{
          href: '/uploads/new',
          label: 'Upload your first repo',
        }}
      />
    </div>
  );
}
