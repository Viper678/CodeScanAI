'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';

import { ThemeProvider } from '@/components/theme-provider';

type ProvidersProps = {
  children: ReactNode;
};

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // The auth/me query handles 401 internally; treat other failures as
        // worth surfacing immediately rather than retrying behind the user's
        // back. Per-query overrides can opt in to retries.
        refetchOnWindowFocus: false,
        retry: false,
      },
    },
  });
}

export function Providers({ children }: Readonly<ProvidersProps>) {
  // useState ensures one client per browser session; recreating on every
  // render would dump the cache.
  const [queryClient] = useState(makeQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider
        attribute="class"
        defaultTheme="system"
        enableSystem
        disableTransitionOnChange
      >
        {children}
      </ThemeProvider>
    </QueryClientProvider>
  );
}
