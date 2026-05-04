'use client';

import { useInfiniteQuery, useQuery } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { fetchFindings } from '@/lib/api/findings/client';
import type {
  FindingsFilters,
  FindingsListResponse,
} from '@/lib/api/findings/types';

export const FINDINGS_QUERY_KEY = 'findings' as const;
export const FINDINGS_FOR_FILE_QUERY_KEY = 'findings-for-file' as const;

type UseFindingsInfiniteOptions = {
  enabled?: boolean;
  limit?: number;
};

/**
 * Cursor-paginated infinite query for `GET /scans/{id}/findings`.
 *
 * The query key intentionally folds the active filters in so toggling a
 * severity chip starts a fresh paginated stream instead of appending to the
 * previous one. `getNextPageParam` reads `next_cursor` from each page; when
 * the server returns `null`, TanStack Query stops calling for more.
 */
export function useFindingsInfinite(
  scanId: string | null,
  filters: FindingsFilters,
  { enabled = true, limit = 50 }: UseFindingsInfiniteOptions = {},
) {
  return useInfiniteQuery<
    FindingsListResponse,
    ApiError,
    { pageParams: (string | null)[]; pages: FindingsListResponse[] },
    readonly unknown[],
    string | null
  >({
    enabled: enabled && scanId !== null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    initialPageParam: null,
    queryFn: ({ pageParam, signal }) =>
      fetchFindings(
        scanId as string,
        { ...filters, cursor: pageParam, limit },
        signal,
      ),
    queryKey: [
      FINDINGS_QUERY_KEY,
      scanId,
      filters.severity.join(',') || null,
      filters.scan_type.join(',') || null,
      filters.file_id ?? null,
      limit,
    ],
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 0,
  });
}

/**
 * Single-page findings query scoped to one file (used by the file viewer
 * sidebar in T4.3). The infinite version above is the wrong shape here:
 * a single file's findings list is small and the viewer wants a flat
 * array, not a `pages` accumulator.
 *
 * The query is disabled when `scanId` is null (e.g. the viewer was
 * opened without a `scan_id` query param). Limit is set high enough to
 * avoid pagination — if a single file ever exceeds 200 findings, we'll
 * surface a "load more" affordance and keep the rest of the UI sane.
 */
export function useFindingsForFile(
  scanId: string | null,
  fileId: string,
  { enabled = true, limit = 200 }: { enabled?: boolean; limit?: number } = {},
) {
  return useQuery<FindingsListResponse, ApiError>({
    enabled: enabled && scanId !== null,
    queryFn: ({ signal }) =>
      fetchFindings(
        scanId as string,
        {
          cursor: null,
          file_id: fileId,
          limit,
          scan_type: [],
          severity: [],
        },
        signal,
      ),
    queryKey: [FINDINGS_FOR_FILE_QUERY_KEY, scanId, fileId, limit],
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 30_000,
  });
}
