import type { ReactNode } from 'react';

import { AppShell } from '@/components/app-shell/app-shell';

export default function AppLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return <AppShell>{children}</AppShell>;
}
