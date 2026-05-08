'use client';

import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import {
  cancelScan,
  createScan,
  deleteScan,
  fetchScan,
  fetchScanFiles,
  fetchScans,
  rerunScan,
} from '@/lib/api/scans/client';
import type {
  ScanCreateRequest,
  ScanCreateResponse,
  ScanDetail,
  ScanFilesResponse,
  ScanListResponse,
  ScanStatus,
} from '@/lib/api/scans/types';

export const SCAN_QUERY_KEY = 'scan' as const;
export const SCAN_FILES_QUERY_KEY = 'scan-files' as const;
export const SCANS_LIST_QUERY_KEY = 'scans-list' as const;

const TERMINAL_STATUSES: ReadonlySet<ScanStatus> = new Set([
  'completed',
  'failed',
  'cancelled',
]);

/**
 * Mutation wrapper around `POST /scans`. Pairs with the Step 4 confirm card
 * which routes to `/scans/{id}` on success and surfaces a mapped error banner
 * on failure (see `confirm-step.tsx`).
 */
export function useCreateScanMutation() {
  return useMutation<ScanCreateResponse, ApiError, ScanCreateRequest>({
    mutationFn: (body) => createScan(body),
  });
}

type ScanPollingOptions = {
  /**
   * Fired exactly once when the scan reaches a terminal state
   * (`completed` / `failed` / `cancelled`). Use a ref-guarded one-shot pattern
   * to avoid double-firing across re-renders.
   */
  onTerminal?: (scan: ScanDetail) => void;
};

/**
 * Polls `GET /scans/{id}` and stops on terminal states. Cadence per
 * docs/FLOW.md §"What the user sees during a scan":
 *
 * - `running`   → 2_000 ms
 * - `pending`   → 5_000 ms
 * - terminal    → no poll
 * - first load  → 1_000 ms (so a freshly-mounted page doesn't sit empty)
 */
export function useScanPolling(
  scanId: string | null,
  options: ScanPollingOptions = {},
) {
  const { onTerminal } = options;
  const query = useQuery<ScanDetail, ApiError>({
    enabled: scanId !== null,
    queryFn: ({ signal }) => fetchScan(scanId as string, signal),
    queryKey: [SCAN_QUERY_KEY, scanId],
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return 1_000;
      if (TERMINAL_STATUSES.has(data.status)) return false;
      if (data.status === 'running') return 2_000;
      if (data.status === 'pending') return 5_000;
      return 1_000;
    },
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 0,
  });

  // One-shot terminal callback. Keyed by `${id}:${status}` so a status
  // transition (pending→running→completed) only fires once on the final flip.
  const firedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!query.data) return;
    if (!TERMINAL_STATUSES.has(query.data.status)) return;
    const key = `${query.data.id}:${query.data.status}`;
    if (firedRef.current === key) return;
    firedRef.current = key;
    onTerminal?.(query.data);
  }, [query.data, onTerminal]);

  return query;
}

type RecentScanFilesOptions = {
  /** Disable the query when the scan is terminal (no more rows will land). */
  enabled: boolean;
  limit?: number;
};

/**
 * Polls `GET /scans/{id}/files` every 3s while enabled. Disable from the
 * caller once the scan is terminal so the tail freezes.
 */
export function useRecentScanFiles(
  scanId: string | null,
  { enabled, limit = 10 }: RecentScanFilesOptions,
) {
  return useQuery<ScanFilesResponse, ApiError>({
    enabled: enabled && scanId !== null,
    queryFn: ({ signal }) => fetchScanFiles(scanId as string, limit, signal),
    queryKey: [SCAN_FILES_QUERY_KEY, scanId, limit],
    refetchInterval: enabled ? 3_000 : false,
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 0,
  });
}

/**
 * Mutation wrapper around `POST /scans/{id}/cancel`. On success, invalidates
 * the polling key so the next refetch reflects `cancelled` immediately rather
 * than waiting for the 5s pending-cadence tick.
 */
export function useCancelScanMutation(scanId: string | null) {
  const queryClient = useQueryClient();
  return useMutation<ScanDetail, ApiError, void>({
    mutationFn: () => {
      if (scanId === null) {
        throw new Error('cannot cancel without a scan id');
      }
      return cancelScan(scanId);
    },
    onSuccess: (data) => {
      // Push the cancel response into the cache directly so the UI flips to
      // 'cancelled' on the next render, then invalidate to be sure a freshly
      // mounted observer doesn't see stale data.
      queryClient.setQueryData([SCAN_QUERY_KEY, scanId], data);
      void queryClient.invalidateQueries({
        queryKey: [SCAN_QUERY_KEY, scanId],
      });
    },
  });
}

type UseScansQueryParams = {
  limit?: number;
  offset?: number;
  /**
   * Multi-select status filter. Comma-joined on the wire, so the cache key
   * sorts before joining to keep the key stable across array order. Empty
   * array → no filter.
   */
  status?: ScanStatus[];
  upload_id?: string;
};

/**
 * One-shot fetch for `GET /scans`. The hook does not poll. Mirrors the
 * surface of the other read hooks in this file (`staleTime: 0`,
 * `retry: false`, no focus refetch). Filters land via
 * `useScansFilters` → `?status=` and are forwarded as a comma-joined value
 * by `fetchScans`.
 */
export function useScansQuery({
  limit = 20,
  offset = 0,
  status = [],
  upload_id,
}: UseScansQueryParams = {}) {
  // Sort the status tuple so [running, completed] and [completed, running]
  // share a cache entry — the server treats them as the same filter.
  const statusKey = [...status].sort().join(',');
  return useQuery<ScanListResponse, ApiError>({
    queryFn: ({ signal }) =>
      fetchScans({ limit, offset, status, upload_id }, signal),
    queryKey: [
      SCANS_LIST_QUERY_KEY,
      limit,
      offset,
      statusKey,
      upload_id ?? null,
    ],
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 0,
  });
}

/**
 * Mutation wrapper around `POST /scans/{id}/rerun`. On success, invalidates
 * the listing cache so the new scan appears as soon as the user returns to
 * `/scans`. Caller routes to `/scans/{new_id}` on the resolved response so
 * the T3.6 progress page takes over.
 */
export function useRerunScanMutation() {
  const queryClient = useQueryClient();
  return useMutation<ScanCreateResponse, ApiError, string>({
    mutationFn: (sourceScanId: string) => rerunScan(sourceScanId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: [SCANS_LIST_QUERY_KEY],
      });
    },
  });
}

/**
 * Mutation wrapper around `DELETE /scans/{id}`. On success, invalidates the
 * scans listing so the deleted row drops out on the next render. We do NOT
 * touch the per-scan detail key — the caller already navigated away (or the
 * row is gone), and a fresh observer mounting against a deleted id will get
 * a 404 from the next poll, which the existing error panel handles.
 */
export function useDeleteScanMutation() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (scanId: string) => deleteScan(scanId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: [SCANS_LIST_QUERY_KEY],
      });
    },
  });
}
