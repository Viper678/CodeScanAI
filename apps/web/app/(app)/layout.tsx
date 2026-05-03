import type { ReactNode } from 'react';

import { AppShell } from '@/components/app-shell/app-shell';
import { RequireAuth } from '@/components/auth/require-auth';

export default function AppLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <RequireAuth>
      <AppShell>{children}</AppShell>
    </RequireAuth>
  );
}
