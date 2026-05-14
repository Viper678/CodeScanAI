'use client';

import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { fetchScans } from '@/lib/api/scans/client';
import type { ScanListResponse } from '@/lib/api/scans/types';
import {
  deleteUpload,
  fetchUpload,
  fetchUploads,
  uploadFile,
  type UploadProgressCallback,
} from '@/lib/api/uploads/client';
import type {
  CreateUploadResponse,
  Upload,
  UploadKind,
  UploadListResponse,
} from '@/lib/api/uploads/types';
import { SCANS_LIST_QUERY_KEY } from '@/lib/api/scans/use-scans';

export const UPLOAD_QUERY_KEY = 'upload' as const;
export const UPLOADS_LIST_QUERY_KEY = 'uploads-list' as const;

/** Variables passed into the upload mutation. */
export type UploadMutationInput = {
  file: File;
  kind: UploadKind;
  onProgress?: UploadProgressCallback;
  signal?: AbortSignal;
};

/**
 * Mutation wrapper around the XHR-based `uploadFile` so callers can plug
 * upload progress into TanStack Query's familiar mutation lifecycle.
 *
 * Cancellation is the caller's responsibility — pass a fresh AbortSignal
 * per attempt and abort it (or unmount the component) to drop in-flight bytes.
 */
export function useUploadMutation() {
  return useMutation<CreateUploadResponse, ApiError, UploadMutationInput>({
    mutationFn: ({ file, kind, onProgress, signal }) =>
      uploadFile({ file, kind, onProgress, signal }),
  });
}

type UploadPollingOptions = {
  enabled: boolean;
  onReady?: (upload: Upload) => void;
  onFailed?: (upload: Upload) => void;
};

/**
 * Polls `GET /uploads/{id}` every ~1s until the upload reaches a terminal
 * state (`ready` or `failed`). Stops polling automatically on those states
 * and fires the matching callback exactly once.
 *
 * The hook is fully cancellable: setting `enabled=false` or unmounting will
 * stop the next poll, and TanStack Query passes its own AbortSignal into the
 * request so any in-flight fetch is aborted too.
 */
export function useUploadPolling(
  uploadId: string | null,
  { enabled, onReady, onFailed }: UploadPollingOptions,
) {
  const query = useQuery<Upload, ApiError>({
    enabled: enabled && uploadId !== null,
    queryFn: ({ signal }) => fetchUpload(uploadId as string, signal),
    queryKey: [UPLOAD_QUERY_KEY, uploadId],
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return 1_000;
      if (data.status === 'ready' || data.status === 'failed') return false;
      return 1_000;
    },
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 0,
  });

  // Fire callbacks on terminal states. Using a ref guards against firing
  // twice if React re-renders before the next refetchInterval check.
  const firedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!query.data) return;
    const key = `${query.data.id}:${query.data.status}`;
    if (firedRef.current === key) return;
    if (query.data.status === 'ready') {
      firedRef.current = key;
      onReady?.(query.data);
    } else if (query.data.status === 'failed') {
      firedRef.current = key;
      onFailed?.(query.data);
    }
  }, [query.data, onReady, onFailed]);

  return query;
}

import type { UploadStatus } from '@/lib/api/uploads/types';

type UseUploadsQueryParams = {
  limit?: number;
  offset?: number;
  /** Optional server-side status filter (``?status=ready``).
   *
   *  Without this, the new-scan wizard's "Use existing" picker would
   *  client-side filter the first ``limit`` rows — which mis-renders the
   *  "no ready uploads" empty state if the latest N happen to be
   *  extracting/failed but an older ready upload exists. Filter in SQL
   *  to keep the empty state honest. Codex P2 on PR #66.
   */
  status?: UploadStatus;
};

/**
 * One-shot fetch for `GET /uploads`. The `/uploads` index renders a single
 * page of rows; pagination controls are out of scope for this iteration so
 * the hook does not poll or refetch on focus. Mirrors the surface of the
 * other read hooks in this file (`staleTime: 0`, `retry: false`).
 */
export function useUploadsQuery({
  limit = 20,
  offset = 0,
  status,
}: UseUploadsQueryParams = {}) {
  return useQuery<UploadListResponse, ApiError>({
    queryFn: ({ signal }) => fetchUploads({ limit, offset, status }, signal),
    queryKey: [UPLOADS_LIST_QUERY_KEY, limit, offset, status],
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 0,
  });
}

/**
 * Per-upload delete-impact counters used to warn the user that hitting
 * "Delete" will also cascade through scans + findings (server-side cascade
 * is in `docs/API.md` §`DELETE /uploads/{id}`). The counters come from
 * existing endpoints — `GET /scans?upload_id=` for the scan rows plus their
 * `summary.by_severity` aggregates — so this is a read-only hook that
 * doesn't need a dedicated backend route.
 *
 * The hook is intentionally lazy: pass `enabled=false` while the delete
 * button is idle so we don't fan out an N+1 of scan queries on every list
 * render. The caller flips `enabled` true the moment the user arms the
 * destructive action (i.e. clicks the trash trigger).
 */
export type UploadDeleteImpact = {
  scanCount: number;
  findingCount: number;
  // false when the upload has more scans than we paged through — the warning
  // helper falls back to the no-counts copy in that case, so we never
  // *understate* the finding total to the user (the cascade is irreversible).
  complete: boolean;
};

export function useUploadDeleteImpact(
  uploadId: string | undefined,
  { enabled }: { enabled: boolean },
) {
  return useQuery<UploadDeleteImpact, ApiError>({
    enabled: enabled && !!uploadId,
    queryFn: async ({ signal }) => {
      const res: ScanListResponse = await fetchScans(
        { limit: 100, upload_id: uploadId },
        signal,
      );
      let findings = 0;
      for (const scan of res.items) {
        for (const count of Object.values(scan.summary.by_severity)) {
          findings += count ?? 0;
        }
      }
      return {
        findingCount: findings,
        scanCount: res.total,
        complete: res.total <= res.items.length,
      };
    },
    queryKey: [UPLOADS_LIST_QUERY_KEY, 'delete-impact', uploadId],
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 0,
  });
}

/**
 * Mutation wrapper around `DELETE /uploads/{id}`. Used by the data-retention
 * delete button on `/uploads` rows + the upload tree-preview header. On
 * success we invalidate both the uploads listing AND the scans listing —
 * an upload delete cascades server-side through its scans + findings, so
 * any cached `/scans` index would otherwise show ghost rows.
 */
export function useDeleteUploadMutation() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (uploadId: string) => deleteUpload(uploadId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: [UPLOADS_LIST_QUERY_KEY],
      });
      void queryClient.invalidateQueries({
        queryKey: [SCANS_LIST_QUERY_KEY],
      });
    },
  });
}
