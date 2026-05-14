import type { ApiErrorBody, ApiErrorDetail } from '@/lib/api/auth/types';

/**
 * An error thrown when the auth API returns a non-2xx response.
 *
 * Carries the parsed error envelope from docs/API.md when present so callers
 * can map specific codes to UI messages without re-parsing.
 */
export class ApiError extends Error {
  public readonly status: number;
  public readonly code: string;
  public readonly details: ReadonlyArray<ApiErrorDetail>;

  public constructor(
    status: number,
    code: string,
    message: string,
    details: ReadonlyArray<ApiErrorDetail> = [],
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** Type guard for our standard API error envelope. */
function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null) return false;
  const body = value as { error?: unknown };
  if (typeof body.error !== 'object' || body.error === null) return false;
  const inner = body.error as { code?: unknown; message?: unknown };
  return typeof inner.code === 'string' && typeof inner.message === 'string';
}

/**
 * Build an ApiError from a fetch Response.
 *
 * Tries to parse the standard error envelope; falls back to a generic message
 * keyed off the HTTP status when the body is missing or malformed.
 */
export async function apiErrorFromResponse(
  response: Response,
): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // body wasn't JSON — fall through to generic
  }

  if (isApiErrorBody(body)) {
    return new ApiError(
      response.status,
      body.error.code,
      body.error.message,
      body.error.details ?? [],
    );
  }

  return new ApiError(
    response.status,
    'unknown_error',
    `Request failed with status ${response.status}.`,
  );
}
