import { ApiError, apiErrorFromResponse } from '@/lib/api/auth/errors';

/** CSRF header required on mutating requests per docs/API.md. */
export const CSRF_HEADER = 'X-Requested-With';
export const CSRF_VALUE = 'codescan';

const DEFAULT_BASE_URL = 'http://localhost:8000/api/v1';

export function getApiBaseUrl(): string {
  // process.env access is hard-coded so Next.js can inline it at build time.
  const fromEnv = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (fromEnv && fromEnv.length > 0) {
    return fromEnv.replace(/\/$/, '');
  }
  return DEFAULT_BASE_URL;
}

type RequestOptions = {
  /** Whether to include the CSRF header. Required for POST/DELETE. */
  csrf?: boolean;
  /** JSON body to send. Will be stringified and Content-Type set. */
  json?: unknown;
  method?: 'GET' | 'POST' | 'DELETE' | 'PATCH' | 'PUT';
  signal?: AbortSignal;
};

/**
 * Issue a fetch request against the CodeScan API.
 *
 * - Always sends cookies (httpOnly session lives there).
 * - Adds the X-Requested-With CSRF header on opt-in.
 * - Throws ApiError for non-2xx responses.
 * - Returns parsed JSON, or `null` for empty (204) bodies.
 */
export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { csrf = false, json, method = 'GET', signal } = options;

  const headers = new Headers();
  if (json !== undefined) {
    headers.set('Content-Type', 'application/json');
  }
  if (csrf) {
    headers.set(CSRF_HEADER, CSRF_VALUE);
  }
  headers.set('Accept', 'application/json');

  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    body: json === undefined ? undefined : JSON.stringify(json),
    credentials: 'include',
    headers,
    method,
    signal,
  });

  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }

  if (response.status === 204) {
    return null as T;
  }

  // Some endpoints might legitimately return empty bodies; guard for that too.
  const text = await response.text();
  if (text.length === 0) {
    return null as T;
  }
  return JSON.parse(text) as T;
}

export { ApiError };
