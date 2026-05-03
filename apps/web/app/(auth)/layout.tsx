import type { ReactNode } from 'react';

import { RequireGuest } from '@/components/auth/require-guest';

export default function AuthLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <RequireGuest>
      <main className="flex min-h-screen items-center justify-center bg-background px-4 py-8">
        {children}
      </main>
    </RequireGuest>
  );
}
