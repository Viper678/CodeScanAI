import { FileUp } from 'lucide-react';

import { EmptyState } from '@/components/empty-state';

export default function UploadsPage() {
  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-semibold tracking-tight">Uploads</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Uploaded archives and loose-file batches will appear here once T2.x
          lands.
        </p>
      </div>

      <EmptyState
        icon={FileUp}
        title="No uploads yet"
        description="Bring in a repository archive or a small file set to seed the scan wizard and file tree."
        action={{
          href: '/scans/new',
          label: 'Start from a new scan',
        }}
      />
    </div>
  );
}
