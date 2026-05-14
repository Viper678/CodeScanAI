'use client';

import { useQuery } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { fetchFileContent } from '@/lib/api/file-content/client';

export const FILE_CONTENT_QUERY_KEY = 'file-content' as const;

/**
 * Cached fetch of a file's raw text content.
 *
 * `staleTime: Infinity` is correct here: extracts are immutable per
 * (upload_id, file_id), so the only legitimate refetches are on remount
 * after navigation. We also opt out of `retry` for 413/415 — those are
 * deterministic failures (file too large / binary) and retrying just
 * delays the friendly fallback rendering.
 */
export function useFileContent(uploadId: string, fileId: string) {
  return useQuery<string, ApiError>({
    queryFn: ({ signal }) => fetchFileContent(uploadId, fileId, signal),
    queryKey: [FILE_CONTENT_QUERY_KEY, uploadId, fileId],
    refetchOnWindowFocus: false,
    retry: (failureCount, error) => {
      if (
        error instanceof ApiError &&
        (error.status === 413 || error.status === 415)
      ) {
        return false;
      }
      return failureCount < 1;
    },
    staleTime: Infinity,
  });
}
