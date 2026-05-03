import { apiFetch } from '@/lib/api/client';
import type { AuthCredentials, AuthUser } from '@/lib/api/auth/types';

/**
 * The auth API client. Each function maps 1:1 to an endpoint in docs/API.md
 * §Auth. Cookies (cs_access / cs_refresh) are managed server-side; we never
 * read or store JWTs on the client.
 */

export async function register(
  credentials: AuthCredentials,
): Promise<AuthUser> {
  return apiFetch<AuthUser>('/auth/register', {
    csrf: true,
    json: credentials,
    method: 'POST',
  });
}

export async function login(credentials: AuthCredentials): Promise<AuthUser> {
  return apiFetch<AuthUser>('/auth/login', {
    csrf: true,
    json: credentials,
    method: 'POST',
  });
}

export async function logout(): Promise<void> {
  await apiFetch<null>('/auth/logout', {
    csrf: true,
    method: 'POST',
  });
}

export async function fetchMe(signal?: AbortSignal): Promise<AuthUser> {
  return apiFetch<AuthUser>('/auth/me', { method: 'GET', signal });
}
