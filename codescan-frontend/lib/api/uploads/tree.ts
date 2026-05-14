'use client';

import { useQuery } from '@tanstack/react-query';

import { ApiError, apiFetch } from '@/lib/api/client';

import type { TreeResponse } from './tree-types';

/**
 * Fetch the materialized file tree for an upload. Maps to
 * `GET /uploads/{id}/tree` (docs/API.md §Uploads).
 */
export async function fetchUploadTree(
  uploadId: string,
  signal?: AbortSignal,
): Promise<TreeResponse> {
  return apiFetch<TreeResponse>(`/uploads/${uploadId}/tree`, {
    method: 'GET',
    signal,
  });
}

/** Cache key per CONTRIBUTING.md §State conventions. */
export const uploadTreeQueryKey = (uploadId: string) =>
  ['uploads', uploadId, 'tree'] as const;

/**
 * TanStack Query hook for the upload tree. Treats 404 as "upload not found"
 * and surfaces the error rather than retrying — the user will see a clear
 * empty/error state.
 */
export function useUploadTree(uploadId: string | undefined) {
  return useQuery<TreeResponse, ApiError>({
    enabled: Boolean(uploadId),
    queryFn: ({ signal }) => fetchUploadTree(uploadId!, signal),
    queryKey: uploadId ? uploadTreeQueryKey(uploadId) : ['uploads', '', 'tree'],
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: 30_000,
  });
}
