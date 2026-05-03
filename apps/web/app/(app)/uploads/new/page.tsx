'use client';

import { useCallback, useState } from 'react';

import { Stepper } from '@/components/stepper';
import { UploadStep } from '@/components/upload/upload-step';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import type { Upload } from '@/lib/api/uploads/types';

const UPLOAD_STEPS = ['Upload', 'Select files'];

export default function NewUploadPage() {
  const [upload, setUpload] = useState<Upload | null>(null);

  const handleReady = useCallback((next: Upload) => {
    setUpload(next);
  }, []);

  const currentStep = upload ? 1 : 0;

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-semibold tracking-tight">New upload</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Upload a repository archive, then choose which files to scan.
        </p>
      </div>

      <Stepper steps={UPLOAD_STEPS} currentStep={currentStep} />

      {upload ? (
        <Card className="border-border/80">
          <CardHeader>
            <CardTitle className="text-base font-medium">
              Step 2 — Select files
            </CardTitle>
            <CardDescription>
              {upload.original_name} is ready. Pick which files to include in
              the scan.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl
              data-testid="upload-summary"
              className="grid gap-4 rounded-2xl border border-border/80 bg-card/60 p-4 sm:grid-cols-3"
            >
              <div>
                <dt className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                  Upload ID
                </dt>
                <dd
                  className="mt-1 truncate font-mono text-xs text-foreground"
                  title={upload.id}
                >
                  {upload.id}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                  Files found
                </dt>
                <dd className="mt-1 text-sm text-foreground">
                  {upload.file_count ?? '—'}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                  Scannable
                </dt>
                <dd className="mt-1 text-sm text-foreground">
                  {upload.scannable_count ?? '—'}
                </dd>
              </div>
            </dl>
            <p className="mt-4 rounded-xl border border-dashed border-border/80 bg-muted/15 px-4 py-3 text-xs text-muted-foreground">
              Tree component lands in T2.5.
            </p>
          </CardContent>
        </Card>
      ) : (
        <UploadStep onReady={handleReady} />
      )}
    </div>
  );
}
