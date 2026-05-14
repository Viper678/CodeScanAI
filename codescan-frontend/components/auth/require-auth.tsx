'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';

import { useSession } from '@/lib/api/auth/use-session';
import { buildLoginRedirect } from '@/lib/auth/redirect';

type RequireAuthProps = {
  children: ReactNode;
};

/**
 * Client-side guard for the (app) route group.
 *
 * Trade-off: API.md describes httpOnly cookies which Next.js server
 * components can't currently introspect without a full server-side proxy
 * (out of scope for T1.3). We resolve the session on mount via the
 * /auth/me query and redirect to /login when it comes back unauthenticated.
 * Until the query settles we render a minimal placeholder so we don't flash
 * gated content.
 */
export function RequireAuth({ children }: Readonly<RequireAuthProps>) {
  const router = useRouter();
  const pathname = usePathname();
  const { isAuthenticated, isLoading } = useSession();

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      router.replace(buildLoginRedirect(pathname ?? ''));
    }
  }, [isAuthenticated, isLoading, pathname, router]);

  if (isLoading || !isAuthenticated) {
    return (
      <div
        aria-hidden
        className="min-h-screen bg-background"
        data-testid="auth-pending"
      />
    );
  }

  return <>{children}</>;
}
