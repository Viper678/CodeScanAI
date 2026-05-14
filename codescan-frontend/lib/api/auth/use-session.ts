'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { fetchMe, login, logout, register } from '@/lib/api/auth/client';
import type { AuthCredentials, AuthUser } from '@/lib/api/auth/types';

/** TanStack Query key for the current session. */
export const SESSION_QUERY_KEY = ['session'] as const;

type UseSessionResult = {
  user: AuthUser | null;
  isAuthenticated: boolean;
  /** True on the very first load before the session has resolved. */
  isLoading: boolean;
  /** True on background refetches; useful for subtler UI states. */
  isFetching: boolean;
};

/**
 * Resolve the current session by calling GET /auth/me.
 *
 * The httpOnly cookie is the source of truth for whether the user is signed
 * in; this hook turns that into a React-friendly value. A 401 is treated as
 * "logged out" rather than an error so callers can branch on
 * `isAuthenticated` without try/catch.
 */
export function useSession(): UseSessionResult {
  const query = useQuery<AuthUser | null, ApiError>({
    queryFn: async ({ signal }) => {
      try {
        return await fetchMe(signal);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          return null;
        }
        throw error;
      }
    },
    queryKey: SESSION_QUERY_KEY,
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 60_000,
  });

  return {
    isAuthenticated: query.data !== null && query.data !== undefined,
    isFetching: query.isFetching,
    isLoading: query.isPending,
    user: query.data ?? null,
  };
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation<AuthUser, ApiError, AuthCredentials>({
    mutationFn: login,
    onSuccess: (user) => {
      queryClient.setQueryData(SESSION_QUERY_KEY, user);
    },
  });
}

export function useRegister() {
  const queryClient = useQueryClient();
  return useMutation<AuthUser, ApiError, AuthCredentials>({
    mutationFn: register,
    onSuccess: (user) => {
      queryClient.setQueryData(SESSION_QUERY_KEY, user);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: logout,
    onSettled: () => {
      // Whether the network call succeeded or not, locally treat the user as
      // logged out so the UI navigates away.
      queryClient.setQueryData(SESSION_QUERY_KEY, null);
    },
  });
}
