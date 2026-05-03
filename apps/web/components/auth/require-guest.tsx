'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';

import { useSession } from '@/lib/api/auth/use-session';
import { resolvePostLoginDestination } from '@/lib/auth/redirect';

type RequireGuestProps = {
  children: ReactNode;
};

/**
 * Inverse of RequireAuth: keeps already-signed-in users out of /login and
 * /register. Honors `?from=<path>` so a user who followed a deep link, then
 * realised they were already signed in, still ends up at the right page.
 */
export function RequireGuest({ children }: Readonly<RequireGuestProps>) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated, isLoading } = useSession();

  useEffect(() => {
    if (isLoading) return;
    if (isAuthenticated) {
      const from = searchParams?.get('from') ?? null;
      router.replace(resolvePostLoginDestination(from));
    }
  }, [isAuthenticated, isLoading, router, searchParams]);

  if (isLoading || isAuthenticated) {
    return (
      <div
        aria-hidden
        className="min-h-screen bg-background"
        data-testid="guest-pending"
      />
    );
  }

  return <>{children}</>;
}
