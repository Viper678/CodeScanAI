'use client';

import { useMutation } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/client';
import { createScan } from '@/lib/api/scans/client';
import type {
  ScanCreateRequest,
  ScanCreateResponse,
} from '@/lib/api/scans/types';

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
