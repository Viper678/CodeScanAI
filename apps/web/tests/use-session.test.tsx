import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/client';
import { useSession } from '@/lib/api/auth/use-session';

const { fetchMeMock } = vi.hoisted(() => ({ fetchMeMock: vi.fn() }));

vi.mock('@/lib/api/auth/client', () => ({
  fetchMe: (signal?: AbortSignal) => fetchMeMock(signal),
  login: vi.fn(),
  logout: vi.fn(),
  register: vi.fn(),
}));

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  };
}

afterEach(() => {
  fetchMeMock.mockReset();
});

describe('useSession', () => {
  it('reports the user as authenticated when /auth/me returns 200', async () => {
    fetchMeMock.mockResolvedValueOnce({
      email: 'user@example.com',
      id: 'user-1',
    });

    const { result } = renderHook(() => useSession(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.user).toEqual({
      email: 'user@example.com',
      id: 'user-1',
    });
  });

  it('reports the user as unauthenticated on a 401', async () => {
    fetchMeMock.mockRejectedValueOnce(
      new ApiError(401, 'unauthorized', 'unauthorized'),
    );

    const { result } = renderHook(() => useSession(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
  });

  it('treats non-401 errors as still-resolved-but-unauthenticated', async () => {
    // Surface non-auth failures through the query error, but for the public
    // shape we still want a defined user (null) and !isAuthenticated. Suppress
    // the expected console.error from React Query so test output stays clean.
    const consoleSpy = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);
    fetchMeMock.mockRejectedValueOnce(
      new ApiError(500, 'internal_error', 'boom'),
    );

    const { result } = renderHook(() => useSession(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
    consoleSpy.mockRestore();
  });
});
