import Link from 'next/link';
import { ArrowRight, ScanLine } from 'lucide-react';

import { EmptyState } from '@/components/empty-state';
import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export default function ScansPage() {
  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight">Scans</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Review your scan history once uploads and execution are wired in.
          </p>
        </div>
        <Link
          href="/scans/new"
          className={cn(
            buttonVariants({ size: 'lg' }),
            'w-full bg-primary text-primary-foreground hover:bg-primary/90 md:w-auto',
          )}
        >
          New scan
          <ArrowRight className="size-4" />
        </Link>
      </div>

      <EmptyState
        icon={ScanLine}
        title="No scans yet"
        description="Create your first static scan to see findings, severity badges, and progress surfaces appear here."
        action={{
          href: '/scans/new',
          label: 'Run your first scan',
        }}
      />
    </div>
  );
}
