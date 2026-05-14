import { ApiError, apiErrorFromResponse } from '@/lib/api/auth/errors';

/** CSRF header required on mutating requests per docs/API.md. */
export const CSRF_HEADER = 'X-Requested-With';
export const CSRF_VALUE = 'codescan';

/**
 * All browser-side API requests use a same-origin relative path. The web
 * container's Next.js ``rewrites()`` (codescan-frontend/next.config.mjs) proxies
 * ``/api/v1/*`` to ``${INTERNAL_API_URL}/*`` server-side, so the runtime
 * api host is never embedded in client bundles. Post-M7 this means one
 * web image deploys to UAT / prod / future staging — only the runtime
 * env var differs. See docs/GCP_MIGRATION.md §M7 + §D4.
 */
export const API_BASE_PATH = '/api/v1';

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

  const response = await fetch(`${API_BASE_PATH}${path}`, {
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
