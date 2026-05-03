'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';

import { FileTree } from '@/components/file-tree/file-tree';
import {
  applyDefaultSelection,
  buildTree,
} from '@/components/file-tree/tree-state';
import { Stepper } from '@/components/stepper';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { UploadStep } from '@/components/upload/upload-step';
import { ApiError } from '@/lib/api/client';
import { useUploadTree } from '@/lib/api/uploads/tree';
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
        <SelectFilesStep upload={upload} />
      ) : (
        <UploadStep onReady={handleReady} />
      )}
    </div>
  );
}

type SelectFilesStepProps = {
  upload: Upload;
};

function SelectFilesStep({ upload }: Readonly<SelectFilesStepProps>) {
  const { data, isPending, error } = useUploadTree(upload.id);

  // Build the tree (and the default selection) once per fresh response. The
  // user's selection then lives in component state — the tree itself doesn't
  // mutate after the upload is ready.
  const tree = useMemo(() => (data ? buildTree(data.files) : null), [data]);

  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [selectionInitialized, setSelectionInitialized] = useState(false);

  useEffect(() => {
    if (tree && !selectionInitialized) {
      setSelection(applyDefaultSelection(tree));
      setSelectionInitialized(true);
    }
  }, [tree, selectionInitialized]);

  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="text-base font-medium">
          Step 2 — Select files
        </CardTitle>
        <CardDescription>
          {upload.original_name} is ready. Pick which files to include in the
          scan.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <dl
          data-testid="upload-summary"
          className="grid gap-4 rounded-2xl border border-border/80 bg-card/60 p-4 sm:grid-cols-4"
        >
          <SummaryItem label="Files found" value={upload.file_count ?? '—'} />
          <SummaryItem
            label="Scannable"
            value={upload.scannable_count ?? '—'}
          />
          <SummaryItem
            label="Selected"
            value={selectionInitialized ? selection.size : '—'}
          />
          <SummaryItem
            label="Upload ID"
            value={upload.id}
            mono
            title={upload.id}
          />
        </dl>

        {isPending ? (
          <div className="flex items-center gap-2 rounded-xl border border-border/80 bg-card/60 p-6 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            Loading file tree…
          </div>
        ) : error ? (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-600 dark:text-red-300"
          >
            <AlertTriangle
              className="mt-0.5 size-4 shrink-0"
              aria-hidden="true"
            />
            <p className="text-sm">
              {error instanceof ApiError
                ? error.message
                : 'Failed to load the file tree.'}
            </p>
          </div>
        ) : data && tree ? (
          <FileTree
            files={data.files}
            selection={selection}
            onSelectionChange={setSelection}
          />
        ) : null}

        <div className="flex items-center justify-between gap-4 border-t border-border/60 pt-4">
          <p className="text-xs text-muted-foreground">
            Configure the scan in the next step (lands with T3.5).
          </p>
          <Button type="button" disabled>
            Continue
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

type SummaryItemProps = {
  label: string;
  value: string | number;
  mono?: boolean;
  title?: string;
};

function SummaryItem({
  label,
  value,
  mono,
  title,
}: Readonly<SummaryItemProps>) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </dt>
      <dd
        className={
          mono
            ? 'mt-1 truncate font-mono text-xs text-foreground'
            : 'mt-1 text-sm text-foreground'
        }
        title={title}
      >
        {value}
      </dd>
    </div>
  );
}
