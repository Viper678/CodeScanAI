'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';

import { ConfirmStep } from '@/components/scan-config/confirm-step';
import { ScanConfigStep } from '@/components/scan-config/scan-config-step';
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
import { DEFAULT_SCAN_CONFIG, type ScanConfigValues } from '@/lib/schemas/scan';

const WIZARD_STEPS = [
  'Upload',
  'Select files',
  'Scan configuration',
  'Confirm & start',
];

/**
 * Wizard step index. The page lifts each step's persistent state so users can
 * navigate back without losing what they typed (file selection, scan config).
 *
 * 0 = Upload, 1 = Select files, 2 = Scan configuration, 3 = Confirm & start.
 */
type WizardStep = 0 | 1 | 2 | 3;

/** Default scan name format: "<upload> – YYYY-MM-DD" (today, in local time). */
function defaultScanName(upload: Upload): string {
  const today = new Date();
  const yyyy = today.getFullYear();
  const mm = String(today.getMonth() + 1).padStart(2, '0');
  const dd = String(today.getDate()).padStart(2, '0');
  return `${upload.original_name} – ${yyyy}-${mm}-${dd}`;
}

export default function NewUploadPage() {
  const [step, setStep] = useState<WizardStep>(0);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [selection, setSelection] = useState<Set<string>>(new Set());
  const [config, setConfig] = useState<ScanConfigValues | null>(null);

  const handleReady = useCallback(
    (next: Upload) => {
      // If the user replaced the upload (different id), reset downstream
      // state so a stale selection from the old upload doesn't follow them
      // into step 2.
      if (upload && upload.id !== next.id) {
        setSelection(new Set());
        setConfig(null);
      }
      setUpload(next);
      setStep(1);
    },
    [upload],
  );

  const handleSelectionContinue = useCallback(() => {
    setStep(2);
  }, []);

  const handleSelectFilesBack = useCallback(() => {
    // Returning to step 1 (Upload). Keep the current upload + selection in
    // case the user just wanted to peek; UploadStep starts fresh, but a new
    // upload in handleReady will reset downstream state.
    setStep(0);
  }, []);

  const handleConfigSubmit = useCallback((next: ScanConfigValues) => {
    setConfig(next);
    setStep(3);
  }, []);

  const initialConfig = useMemo<ScanConfigValues>(() => {
    if (config) return config;
    if (!upload) return DEFAULT_SCAN_CONFIG;
    return { ...DEFAULT_SCAN_CONFIG, name: defaultScanName(upload) };
  }, [config, upload]);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-semibold tracking-tight">New scan</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Upload a repository archive, choose files, configure the scan, and
          start.
        </p>
      </div>

      <Stepper steps={WIZARD_STEPS} currentStep={step} />

      {step === 0 || !upload ? (
        <UploadStep onReady={handleReady} />
      ) : step === 1 ? (
        <SelectFilesStep
          upload={upload}
          selection={selection}
          onSelectionChange={setSelection}
          onBack={handleSelectFilesBack}
          onContinue={handleSelectionContinue}
        />
      ) : step === 2 ? (
        <ScanConfigStep
          upload={upload}
          selectedFileCount={selection.size}
          initialValues={initialConfig}
          onBack={(snapshot) => {
            // Snapshot in-progress edits so the user doesn't lose them when
            // they revisit step 3 after going back to tweak file selection.
            setConfig(snapshot);
            setStep(1);
          }}
          onSubmit={handleConfigSubmit}
        />
      ) : config ? (
        <ConfirmStep
          upload={upload}
          selection={selection}
          config={config}
          onBack={() => setStep(2)}
        />
      ) : null}
    </div>
  );
}

type SelectFilesStepProps = {
  upload: Upload;
  selection: Set<string>;
  onSelectionChange: (next: Set<string>) => void;
  onBack: () => void;
  onContinue: () => void;
};

function SelectFilesStep({
  upload,
  selection,
  onSelectionChange,
  onBack,
  onContinue,
}: Readonly<SelectFilesStepProps>) {
  const { data, isPending, error } = useUploadTree(upload.id);

  // Build the tree (and the default selection) once per fresh response. The
  // user's selection then lives in the page-level state — the tree itself
  // doesn't mutate after the upload is ready.
  const tree = useMemo(() => (data ? buildTree(data.files) : null), [data]);

  const [selectionInitialized, setSelectionInitialized] = useState(
    () => selection.size > 0,
  );

  useEffect(() => {
    if (tree && !selectionInitialized) {
      onSelectionChange(applyDefaultSelection(tree));
      setSelectionInitialized(true);
    }
  }, [tree, selectionInitialized, onSelectionChange]);

  const continueDisabled = !selectionInitialized || selection.size === 0;

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
            onSelectionChange={onSelectionChange}
          />
        ) : null}

        <div className="flex items-center justify-between gap-4 border-t border-border/60 pt-4">
          <Button type="button" variant="outline" onClick={onBack}>
            Back
          </Button>
          <Button
            type="button"
            onClick={onContinue}
            disabled={continueDisabled}
          >
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
