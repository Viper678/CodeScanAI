import { apiFetch } from '@/lib/api/client';
import type {
  ScanCreateRequest,
  ScanCreateResponse,
  ScanDetail,
  ScanFilesResponse,
  ScanListResponse,
  ScanStatus,
} from '@/lib/api/scans/types';

/**
 * POST `/scans` — create a new scan against a previously uploaded archive.
 * Mirrors the contract in docs/API.md §Scans / apps/api/app/schemas/scan.py.
 *
 * The server enforces the cross-field rules (non-empty `scan_types`, keywords
 * required when `"keywords" in scan_types`, file ownership, etc.). The client
 * validates a friendlier subset via zod before POSTing — see
 * `lib/schemas/scan.ts`.
 */
export async function createScan(
  body: ScanCreateRequest,
): Promise<ScanCreateResponse> {
  return apiFetch<ScanCreateResponse>('/scans', {
    csrf: true,
    json: body,
    method: 'POST',
  });
}

/** GET `/scans/{id}` — used by the progress-page poll. */
export async function fetchScan(
  scanId: string,
  signal?: AbortSignal,
): Promise<ScanDetail> {
  return apiFetch<ScanDetail>(`/scans/${scanId}`, { method: 'GET', signal });
}

/**
 * GET `/scans/{id}/files` — recent-files tail for the live progress surface.
 * Caps `limit` to 1..50; the server enforces the same.
 */
export async function fetchScanFiles(
  scanId: string,
  limit: number,
  signal?: AbortSignal,
): Promise<ScanFilesResponse> {
  const safeLimit = Math.min(50, Math.max(1, Math.trunc(limit)));
  return apiFetch<ScanFilesResponse>(
    `/scans/${scanId}/files?limit=${safeLimit}`,
    { method: 'GET', signal },
  );
}

/**
 * POST `/scans/{id}/cancel` — flips a pending/running scan to cancelled.
 * Returns the freshly updated `ScanDetail` (the API mirrors the GET shape on
 * the cancel response, so a successful call lets the caller skip a refetch).
 */
export async function cancelScan(scanId: string): Promise<ScanDetail> {
  return apiFetch<ScanDetail>(`/scans/${scanId}/cancel`, {
    csrf: true,
    method: 'POST',
  });
}

type FetchScansParams = {
  limit?: number;
  offset?: number;
  /**
   * Multi-select status filter. Sent as a comma-joined value on the wire
   * (`?status=running,completed`) per docs/API.md §`GET /scans`. Empty array
   * → param is dropped so the server returns the unfiltered set. Mirrors
   * the findings-client's filter shape so the two filter surfaces stay
   * structurally identical.
   */
  status?: ScanStatus[];
  upload_id?: string;
};

/**
 * GET `/scans?limit=&offset=&status=&upload_id=` — paginated index of the
 * current user's scans. Server caps `limit` to 1..100.
 */
export async function fetchScans(
  { limit = 20, offset = 0, status = [], upload_id }: FetchScansParams = {},
  signal?: AbortSignal,
): Promise<ScanListResponse> {
  const safeLimit = Math.min(100, Math.max(1, Math.trunc(limit)));
  const safeOffset = Math.max(0, Math.trunc(offset));
  const params = new URLSearchParams({
    limit: String(safeLimit),
    offset: String(safeOffset),
  });
  if (status.length > 0) params.set('status', status.join(','));
  if (upload_id) params.set('upload_id', upload_id);
  return apiFetch<ScanListResponse>(`/scans?${params.toString()}`, {
    method: 'GET',
    signal,
  });
}

/**
 * POST `/scans/{id}/rerun` — kick off a new scan with the same inputs as
 * the source. Server reconstructs `file_ids`, `scan_types`, and the keywords
 * config from the source row and returns the **new** scan's id (`202`).
 * See docs/API.md §`POST /scans/{id}/rerun`.
 */
export async function rerunScan(scanId: string): Promise<ScanCreateResponse> {
  return apiFetch<ScanCreateResponse>(`/scans/${scanId}/rerun`, {
    csrf: true,
    method: 'POST',
  });
}

/**
 * DELETE `/scans/{id}` — hard-delete a scan and all its findings + scan_files.
 * Returns 204 (no body); see docs/API.md §`DELETE /scans/{id}`.
 */
export async function deleteScan(scanId: string): Promise<void> {
  await apiFetch<void>(`/scans/${scanId}`, {
    csrf: true,
    method: 'DELETE',
  });
}
