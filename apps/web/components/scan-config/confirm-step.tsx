'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { AlertTriangle, Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { ApiError } from '@/lib/api/client';
import { useCreateScanMutation } from '@/lib/api/scans/use-scans';
import type { ScanCreateRequest, ScanType } from '@/lib/api/scans/types';
import type { Upload } from '@/lib/api/uploads/types';
import {
  normalizeKeywordItems,
  type ScanConfigValues,
} from '@/lib/schemas/scan';

type ConfirmStepProps = {
  upload: Upload;
  selection: ReadonlySet<string>;
  config: ScanConfigValues;
  onBack: () => void;
};

type BannerError = {
  message: string;
  showSignIn?: boolean;
};

const TYPE_LABELS: Record<ScanType, string> = {
  bugs: 'Bug',
  keywords: 'Keyword',
  security: 'Security',
};

/** Map a thrown ApiError to the inline banner message. */
function mapCreateScanError(error: unknown): BannerError {
  if (!(error instanceof ApiError)) {
    return { message: "Couldn't start the scan. Please try again." };
  }
  switch (error.status) {
    case 401:
      return { message: 'Your session expired.', showSignIn: true };
    case 403:
      return {
        message:
          "Some files in this upload aren't accessible. Go back and re-select.",
      };
    case 422:
      return { message: error.message };
    case 503:
      return {
        message:
          'The scan queue is temporarily unavailable. Try again in a moment.',
      };
    default:
      return { message: "Couldn't start the scan. Please try again." };
  }
}

/** Build the request body — drops `keywords` when not part of `scan_types`. */
function buildRequest(
  upload: Upload,
  selection: ReadonlySet<string>,
  config: ScanConfigValues,
): ScanCreateRequest {
  const trimmedName = config.name?.trim() ?? '';
  const body: ScanCreateRequest = {
    file_ids: Array.from(selection),
    model_settings: {},
    name: trimmedName.length > 0 ? trimmedName : null,
    scan_types: config.scan_types,
    upload_id: upload.id,
  };
  if (config.scan_types.includes('keywords')) {
    body.keywords = {
      case_sensitive: config.keywords.case_sensitive,
      items: normalizeKeywordItems(config.keywords.items),
      regex: config.keywords.regex,
    };
  }
  return body;
}

export function ConfirmStep({
  upload,
  selection,
  config,
  onBack,
}: Readonly<ConfirmStepProps>) {
  const router = useRouter();
  const mutation = useCreateScanMutation();
  const [bannerError, setBannerError] = useState<BannerError | null>(null);

  const normalizedKeywords = useMemo(
    () => normalizeKeywordItems(config.keywords.items),
    [config.keywords.items],
  );
  const trimmedName = config.name?.trim() ?? '';

  function handleStart() {
    setBannerError(null);
    const body = buildRequest(upload, selection, config);
    mutation.mutate(body, {
      onError: (error) => {
        setBannerError(mapCreateScanError(error));
      },
      onSuccess: (response) => {
        router.push(`/scans/${response.id}`);
      },
    });
  }

  const showKeywordsBlock = config.scan_types.includes('keywords');

  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="text-base font-medium">
          Step 4 — Confirm &amp; start
        </CardTitle>
        <CardDescription>
          Review the configuration before kicking off the scan.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {bannerError ? (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-600 dark:text-red-300"
          >
            <AlertTriangle
              className="mt-0.5 size-4 shrink-0"
              aria-hidden="true"
            />
            <div className="text-sm">
              <p>{bannerError.message}</p>
              {bannerError.showSignIn ? (
                <p className="mt-1">
                  <Link
                    href="/login"
                    className="font-medium underline underline-offset-4"
                  >
                    Sign in
                  </Link>{' '}
                  to continue.
                </p>
              ) : null}
            </div>
          </div>
        ) : null}

        <dl className="grid gap-4 rounded-2xl border border-border/80 bg-card/60 p-4 sm:grid-cols-2">
          <SummaryItem label="Upload" value={upload.original_name} />
          <SummaryItem label="Upload ID" value={upload.id} mono />
          <SummaryItem
            label="Files"
            value={`${selection.size} of ${upload.scannable_count ?? '—'}`}
          />
          <SummaryItem
            label="Scan name"
            value={trimmedName.length > 0 ? trimmedName : '—'}
          />
        </dl>

        <div className="space-y-2">
          <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
            Scan types
          </p>
          <div className="flex flex-wrap gap-2">
            {config.scan_types.map((type) => (
              <Badge key={type} variant="secondary">
                {TYPE_LABELS[type]}
              </Badge>
            ))}
          </div>
        </div>

        {showKeywordsBlock ? (
          <div className="space-y-2 rounded-2xl border border-border/80 bg-card/60 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
              Keywords
            </p>
            <dl className="grid gap-4 sm:grid-cols-3">
              <SummaryItem label="Patterns" value={normalizedKeywords.length} />
              <SummaryItem
                label="Case sensitive"
                value={config.keywords.case_sensitive ? 'Yes' : 'No'}
              />
              <SummaryItem
                label="Regex"
                value={config.keywords.regex ? 'Yes' : 'No'}
              />
            </dl>
          </div>
        ) : null}

        <div className="flex items-center justify-between gap-4 border-t border-border/60 pt-4">
          <Button type="button" variant="outline" onClick={onBack}>
            Back
          </Button>
          <Button
            type="button"
            onClick={handleStart}
            disabled={mutation.isPending}
          >
            <Sparkles className="size-4" aria-hidden="true" />
            {mutation.isPending ? 'Starting…' : 'Start scan'}
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
};

function SummaryItem({ label, value, mono }: Readonly<SummaryItemProps>) {
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
        title={typeof value === 'string' ? value : undefined}
      >
        {value}
      </dd>
    </div>
  );
}
