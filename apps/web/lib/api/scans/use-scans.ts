'use client';

import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import {
  cancelScan,
  createScan,
  fetchScan,
  fetchScanFiles,
} from '@/lib/api/scans/client';
import type {
  ScanCreateRequest,
  ScanCreateResponse,
  ScanDetail,
  ScanFilesResponse,
  ScanStatus,
} from '@/lib/api/scans/types';

export const SCAN_QUERY_KEY = 'scan' as const;
export const SCAN_FILES_QUERY_KEY = 'scan-files' as const;

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
