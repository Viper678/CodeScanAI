'use client';

import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

import { KeywordsEditor } from '@/components/scan-config/keywords-editor';
import { ScanTypesSection } from '@/components/scan-config/scan-types-section';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { Upload } from '@/lib/api/uploads/types';
import { scanConfigSchema, type ScanConfigValues } from '@/lib/schemas/scan';

type ScanConfigStepProps = {
  upload: Upload;
  selectedFileCount: number;
  /** Initial values — restored when the user revisits this step from step 4. */
  initialValues: ScanConfigValues;
  /**
   * Receives the current (possibly invalid) in-progress values so the page can
   * snapshot them before stepping back. Without this, mid-edit changes
   * (typed scan name, keyword tweaks) are lost on Back → revisit.
   */
  onBack: (snapshot: ScanConfigValues) => void;
  onSubmit: (values: ScanConfigValues) => void;
};

export function ScanConfigStep({
  upload,
  selectedFileCount,
  initialValues,
  onBack,
  onSubmit,
}: Readonly<ScanConfigStepProps>) {
  const {
    control,
    formState: { errors, isSubmitting },
    getValues,
    handleSubmit,
    register,
    watch,
  } = useForm<ScanConfigValues>({
    defaultValues: initialValues,
    mode: 'onSubmit',
    resolver: zodResolver(scanConfigSchema),
  });

  const scanTypes = watch('scan_types');
  const showKeywordsEditor = scanTypes.includes('keywords');

  const submit = handleSubmit((values) => onSubmit(values));

  // TODO(T3.x): surface an "Advanced" collapsed section here for
  // model_settings (temperature, severity threshold). The API accepts the
  // shape today but no current product surface uses it.

  return (
    <Card className="border-border/80">
      <CardHeader>
        <CardTitle className="text-base font-medium">
          Step 3 — Scan configuration
        </CardTitle>
        <CardDescription>
          {selectedFileCount} file{selectedFileCount === 1 ? '' : 's'} selected
          from <span className="font-medium">{upload.original_name}</span>. Pick
          what to look for.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={submit} noValidate>
          <Controller
            control={control}
            name="scan_types"
            render={({ field, fieldState }) => (
              <ScanTypesSection
                value={field.value}
                onChange={field.onChange}
                errorMessage={fieldState.error?.message}
              />
            )}
          />

          {showKeywordsEditor ? (
            <Controller
              control={control}
              name="keywords"
              render={({ field, fieldState }) => {
                // Locate either the items-level error (e.g. "Add at least
                // one") or the first per-pattern regex error so the editor
                // shows something useful.
                const itemsError =
                  fieldState.error?.message ??
                  (
                    fieldState.error as unknown as {
                      items?: { message?: string }[];
                    }
                  )?.items?.find((entry) => entry?.message)?.message;
                return (
                  <KeywordsEditor
                    value={field.value}
                    onChange={field.onChange}
                    itemsError={itemsError}
                  />
                );
              }}
            />
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="scan-name">Scan name</Label>
            <Input
              id="scan-name"
              type="text"
              autoComplete="off"
              placeholder="e.g. Repo audit – 2026-05-03"
              aria-invalid={errors.name ? 'true' : 'false'}
              {...register('name')}
            />
            {errors.name?.message ? (
              <p className="text-sm text-red-500">{errors.name.message}</p>
            ) : null}
          </div>

          <div className="flex items-center justify-between gap-4 border-t border-border/60 pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onBack(getValues())}
            >
              Back
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              Continue
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
