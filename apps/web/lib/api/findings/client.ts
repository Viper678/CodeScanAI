import { apiFetch, getApiBaseUrl } from '@/lib/api/client';
import type {
  ExportFormat,
  FindingsFilters,
  FindingsListResponse,
} from '@/lib/api/findings/types';

/**
 * Build the query-string segment shared by the findings list endpoint and
 * the export endpoint. `severity` and `scan_type` are sent as
 * comma-joined values per docs/API.md §Findings (`?severity=high,critical`).
 * Empty arrays are dropped so the server returns the unfiltered set.
 */
function buildFilterParams(filters: FindingsFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.severity.length > 0) {
    params.set('severity', filters.severity.join(','));
  }
  if (filters.scan_type.length > 0) {
    params.set('scan_type', filters.scan_type.join(','));
  }
  if (filters.file_id) {
    params.set('file_id', filters.file_id);
  }
  return params;
}

type FetchFindingsParams = FindingsFilters & {
  cursor?: string | null;
  limit?: number;
};

/**
 * GET `/scans/{scanId}/findings` with optional filters + cursor pagination.
 * Server caps `limit` to 1..100 — we mirror that cap client-side so a typo
 * in a caller can't issue an obviously bad request.
 */
export async function fetchFindings(
  scanId: string,
  params: FetchFindingsParams,
  signal?: AbortSignal,
): Promise<FindingsListResponse> {
  const { cursor, limit = 50, ...filters } = params;
  const search = buildFilterParams(filters);
  const safeLimit = Math.min(100, Math.max(1, Math.trunc(limit)));
  search.set('limit', String(safeLimit));
  if (cursor) {
    search.set('cursor', cursor);
  }
  return apiFetch<FindingsListResponse>(
    `/scans/${scanId}/findings?${search.toString()}`,
    { method: 'GET', signal },
  );
}

/**
 * Build a fully-qualified URL for `GET /scans/{scanId}/export?fmt=`.
 *
 * The export endpoint streams the response with a `Content-Disposition`
 * header — the natural way to trigger a download is an `<a download href>`.
 * Cookie-based auth means the browser sends the session cookie automatically
 * when the user clicks the link; no JS fetch needed.
 */
export function getExportUrl(
  scanId: string,
  fmt: ExportFormat,
  filters: FindingsFilters,
): string {
  const search = buildFilterParams(filters);
  search.set('fmt', fmt);
  return `${getApiBaseUrl()}/scans/${scanId}/export?${search.toString()}`;
}
