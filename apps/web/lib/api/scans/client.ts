import { apiFetch } from '@/lib/api/client';
import type {
  ScanCreateRequest,
  ScanCreateResponse,
} from '@/lib/api/scans/types';

/**
 * POST `/scans` — create a new scan against a previously uploaded archive.
 * Mirrors the contract in docs/API.md §Scans / apps/api/app/schemas/scan.py.
 *
 * The server enforces the cross-field rules (non-empty `scan_types`, keywords
 * required when `"keywords" in scan_types`, file ownership, etc.). The client
 * validates a friendlier subset via zod before POSTing — see
 * `lib/schemas/scan.ts`.
 */
export async function createScan(
  body: ScanCreateRequest,
): Promise<ScanCreateResponse> {
  return apiFetch<ScanCreateResponse>('/scans', {
    csrf: true,
    json: body,
    method: 'POST',
  });
}
