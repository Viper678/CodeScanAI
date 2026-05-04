'use client';

import { useInfiniteQuery } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { fetchFindings } from '@/lib/api/findings/client';
import type {
  FindingsFilters,
  FindingsListResponse,
} from '@/lib/api/findings/types';

export const FINDINGS_QUERY_KEY = 'findings' as const;

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
