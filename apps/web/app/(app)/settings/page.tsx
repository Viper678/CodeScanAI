import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function SettingsPage() {
  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-3xl font-semibold tracking-tight">Settings</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Profile and session controls are stubbed here until auth management
          ships.
        </p>
      </div>

      <section className="space-y-4">
        <div>
          <h3 className="text-lg font-semibold">Profile</h3>
          <p className="text-sm text-muted-foreground">
            Account details and password management will populate this card
            later.
          </p>
        </div>

        <Card className="max-w-3xl border-border/80">
          <CardHeader>
            <CardTitle className="text-base font-medium">
              Profile details
            </CardTitle>
          </CardHeader>
          <CardContent className="h-32 rounded-b-xl bg-muted/20" />
        </Card>
      </section>
    </div>
  );
}
