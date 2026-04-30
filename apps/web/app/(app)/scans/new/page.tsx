import { Stepper } from '@/components/stepper';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

const SCAN_STEPS = [
  'Upload',
  'Select files',
  'Scan configuration',
  'Confirm & start',
];

export default function NewScanPage() {
  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-semibold tracking-tight">New scan</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The wizard flow is scaffolded here. Upload, file selection, and
          execution arrive in later tasks.
        </p>
      </div>

      <Stepper steps={SCAN_STEPS} currentStep={0} />

      <Card className="border-border/80">
        <CardHeader>
          <CardTitle className="text-base font-medium">
            Step 1 — Upload
          </CardTitle>
          <CardDescription>
            Placeholder surface for the upload dropzone and extraction state.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex min-h-72 items-center justify-center rounded-2xl border border-dashed border-border/80 bg-muted/15 px-6 text-center">
            <div>
              <p className="text-sm font-medium">
                Upload UI will be added in T2.x.
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                This page intentionally stops at the presentational 4-step
                shell.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
