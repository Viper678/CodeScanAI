import {
  ApiError,
  apiFetch,
  CSRF_HEADER,
  CSRF_VALUE,
  getApiBaseUrl,
} from '@/lib/api/client';
import type { ApiErrorBody } from '@/lib/api/auth/types';
import type {
  CreateUploadResponse,
  Upload,
  UploadKind,
} from '@/lib/api/uploads/types';

/**
 * Progress callback for the XHR upload. Receives a fraction in [0, 1] when
 * the request is `lengthComputable`, else `null` so the caller can fall back
 * to an indeterminate state.
 */
export type UploadProgressCallback = (progress: number | null) => void;

type UploadFileArgs = {
  file: File;
  kind: UploadKind;
  onProgress?: UploadProgressCallback;
  signal?: AbortSignal;
};

/** Type guard for the standard API error envelope. */
function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null) return false;
  const body = value as { error?: unknown };
  if (typeof body.error !== 'object' || body.error === null) return false;
  const inner = body.error as { code?: unknown; message?: unknown };
  return typeof inner.code === 'string' && typeof inner.message === 'string';
}

/** Build an ApiError from an XHR response body. */
function apiErrorFromXhr(xhr: XMLHttpRequest): ApiError {
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(xhr.responseText) as unknown;
  } catch {
    // body wasn't JSON — fall through to generic
  }
  if (isApiErrorBody(parsed)) {
    return new ApiError(
      xhr.status,
      parsed.error.code,
      parsed.error.message,
      parsed.error.details ?? [],
    );
  }
  return new ApiError(
    xhr.status,
    'unknown_error',
    `Upload failed with status ${xhr.status}.`,
  );
}

/**
 * POST /uploads via XMLHttpRequest so we can surface upload progress events
 * (which `fetch` does not expose). Resolves with the server's 202 envelope.
 *
 * The mutation honours an optional AbortSignal so the caller can cancel an
 * in-flight upload (e.g. when the user leaves the page or starts over).
 */
export function uploadFile({
  file,
  kind,
  onProgress,
  signal,
}: UploadFileArgs): Promise<CreateUploadResponse> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Upload aborted', 'AbortError'));
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${getApiBaseUrl()}/uploads`);
    xhr.withCredentials = true;
    xhr.setRequestHeader(CSRF_HEADER, CSRF_VALUE);
    xhr.setRequestHeader('Accept', 'application/json');
    // Note: do NOT set Content-Type — the browser sets the correct
    // multipart/form-data header (with boundary) when sending FormData.

    if (onProgress) {
      xhr.upload.onprogress = (event: ProgressEvent) => {
        if (event.lengthComputable) {
          onProgress(event.total === 0 ? null : event.loaded / event.total);
        } else {
          onProgress(null);
        }
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as CreateUploadResponse);
        } catch (parseError) {
          reject(
            new ApiError(
              xhr.status,
              'invalid_response',
              'Upload response was not valid JSON.',
            ),
          );
          // Surface the raw error to the console for debugging without
          // leaking it through the rejected promise.
          // eslint-disable-next-line no-console -- reason: dev visibility on a rare path
          console.error('Failed to parse upload response', parseError);
        }
        return;
      }
      reject(apiErrorFromXhr(xhr));
    };

    xhr.onerror = () => {
      reject(
        new ApiError(0, 'network_error', 'Network error while uploading.'),
      );
    };

    xhr.onabort = () => {
      reject(new DOMException('Upload aborted', 'AbortError'));
    };

    if (signal) {
      signal.addEventListener(
        'abort',
        () => {
          xhr.abort();
        },
        { once: true },
      );
    }

    const form = new FormData();
    form.append('kind', kind);
    form.append('file', file);
    xhr.send(form);
  });
}

/** GET /uploads/{id} — used for polling extraction status. */
export async function fetchUpload(
  id: string,
  signal?: AbortSignal,
): Promise<Upload> {
  return apiFetch<Upload>(`/uploads/${id}`, { method: 'GET', signal });
}
