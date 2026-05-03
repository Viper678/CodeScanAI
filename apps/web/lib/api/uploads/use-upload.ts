'use client';

import { useEffect, useRef } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import {
  fetchUpload,
  uploadFile,
  type UploadProgressCallback,
} from '@/lib/api/uploads/client';
import type {
  CreateUploadResponse,
  Upload,
  UploadKind,
} from '@/lib/api/uploads/types';

export const UPLOAD_QUERY_KEY = 'upload' as const;

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
