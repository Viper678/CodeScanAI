'use client';

import { useCallback, useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import type { ScanStatus } from '@/lib/api/scans/types';
import type { ScansFilters } from '@/lib/api/scans/types';

const STATUSES: ReadonlyArray<ScanStatus> = [
  'pending',
  'running',
  'completed',
  'failed',
  'cancelled',
];

const STATUS_SET = new Set<string>(STATUSES);

/**
 * Parse a comma-joined query value into a typed, validated tuple. Mirrors
 * the findings filter parser: unknown / blank / duplicate tokens silently
 * dropped — a stale link with `status=oldlabel` should fall back to "no
 * filter" rather than 422 the API.
 */
function parseList<T extends string>(
  raw: string | null,
  allowed: ReadonlySet<string>,
): T[] {
  if (!raw) return [];
  const tokens = raw
    .split(',')
    .map((token) => token.trim())
    .filter((token) => token.length > 0);
  const seen = new Set<string>();
  const out: T[] = [];
  for (const token of tokens) {
    if (!allowed.has(token) || seen.has(token)) continue;
    seen.add(token);
    out.push(token as T);
  }
  return out;
}

/** Read filters from `?status=`. Pure for testability. */
export function parseScansFilters(search: URLSearchParams): ScansFilters {
  return {
    status: parseList<ScanStatus>(search.get('status'), STATUS_SET),
  };
}

/**
 * Serialize filters back into a stable query string. Empty arrays are
 * dropped so the URL stays clean and the back/forward stack matches the
 * server's "no filter" semantics.
 */
export function serializeScansFilters(filters: ScansFilters): string {
  const params = new URLSearchParams();
  if (filters.status.length > 0) {
    params.set('status', filters.status.join(','));
  }
  return params.toString();
}

type UseScansFiltersReturn = {
  filters: ScansFilters;
  setFilters: (next: ScansFilters) => void;
  toggleStatus: (status: ScanStatus) => void;
  clearAll: () => void;
};

/**
 * Bind the `/scans` filter state to the URL via `?status=` so the page is
 * shareable and the browser back/forward buttons behave. Mirrors the shape
 * of `useFindingsFilters` (T4.2) so a future second filter dimension drops
 * in without rewriting the surface.
 *
 * Uses `router.replace` (not `push`) so toggling chips doesn't clobber the
 * back stack with intermediate states.
 */
export function useScansFilters(): UseScansFiltersReturn {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const filters = useMemo(
    () => parseScansFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  const setFilters = useCallback(
    (next: ScansFilters) => {
      const qs = serializeScansFilters(next);
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  const toggleStatus = useCallback(
    (status: ScanStatus) => {
      const has = filters.status.includes(status);
      const nextStatus = has
        ? filters.status.filter((s) => s !== status)
        : [...filters.status, status];
      setFilters({ ...filters, status: nextStatus });
    },
    [filters, setFilters],
  );

  const clearAll = useCallback(() => {
    setFilters({ status: [] });
  }, [setFilters]);

  return { clearAll, filters, setFilters, toggleStatus };
}
