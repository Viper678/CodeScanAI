import { ApiError, apiErrorFromResponse } from '@/lib/api/auth/errors';
import { API_BASE_PATH } from '@/lib/api/client';

/**
 * Fetch the raw text content of an uploaded file via
 * `GET /uploads/{upload_id}/files/{file_id}/content`.
 *
 * The endpoint streams `text/plain; charset=utf-8`. We deliberately bypass
 * `apiFetch` here because that helper assumes a JSON envelope on success —
 * we want the raw response body. Errors still go through the same
 * `ApiError` mapping so the viewer can branch on `status === 413|415`
 * for friendly fallbacks.
 */
export async function fetchFileContent(
  uploadId: string,
  fileId: string,
  signal?: AbortSignal,
): Promise<string> {
  const response = await fetch(
    `${API_BASE_PATH}/uploads/${uploadId}/files/${fileId}/content`,
    {
      credentials: 'include',
      headers: { Accept: 'text/plain' },
      method: 'GET',
      signal,
    },
  );
  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }
  return await response.text();
}

export { ApiError };
