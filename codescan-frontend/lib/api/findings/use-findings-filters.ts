'use client';

import { useCallback, useMemo } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

import type { ScanType, Severity } from '@/lib/api/scans/types';
import type { FindingsFilters } from '@/lib/api/findings/types';

const SEVERITIES: ReadonlyArray<Severity> = [
  'critical',
  'high',
  'medium',
  'low',
  'info',
];
const SCAN_TYPES: ReadonlyArray<ScanType> = ['security', 'bugs', 'keywords'];

const SEVERITY_SET = new Set<string>(SEVERITIES);
const SCAN_TYPE_SET = new Set<string>(SCAN_TYPES);

/**
 * Parse a comma-joined query value into a typed, validated tuple. Unknown
 * tokens are silently dropped — a stale link with `severity=oldlabel` should
 * fall back to "no filter" rather than 500 the API.
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

/** Read filters from `?severity=&scan_type=&file_id=`. Pure for testability. */
export function parseFindingsFilters(search: URLSearchParams): FindingsFilters {
  return {
    file_id: search.get('file_id') || null,
    scan_type: parseList<ScanType>(search.get('scan_type'), SCAN_TYPE_SET),
    severity: parseList<Severity>(search.get('severity'), SEVERITY_SET),
  };
}

/**
 * Serialize filters back into a stable query string. Empty buckets are
 * dropped so the URL stays clean and the back/forward stack matches the
 * server's "no filter for this dimension" semantics.
 */
export function serializeFindingsFilters(filters: FindingsFilters): string {
  const params = new URLSearchParams();
  if (filters.severity.length > 0) {
    params.set('severity', filters.severity.join(','));
  }
  if (filters.scan_type.length > 0) {
    params.set('scan_type', filters.scan_type.join(','));
  }
  if (filters.file_id) {
    params.set('file_id', filters.file_id);
  }
  return params.toString();
}

type UseFindingsFiltersReturn = {
  filters: FindingsFilters;
  setFilters: (next: FindingsFilters) => void;
  toggleSeverity: (severity: Severity) => void;
  toggleScanType: (scanType: ScanType) => void;
  clearAll: () => void;
};

/**
 * Bind findings filter state to the URL via `?severity=&scan_type=&file_id=`
 * so the page is shareable and the browser back/forward buttons behave.
 *
 * Uses `router.replace` (not `push`) so toggling filters doesn't clobber the
 * back stack with intermediate states.
 */
export function useFindingsFilters(): UseFindingsFiltersReturn {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const filters = useMemo(
    () => parseFindingsFilters(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  const setFilters = useCallback(
    (next: FindingsFilters) => {
      const qs = serializeFindingsFilters(next);
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  const toggleSeverity = useCallback(
    (severity: Severity) => {
      const has = filters.severity.includes(severity);
      const nextSeverity = has
        ? filters.severity.filter((s) => s !== severity)
        : [...filters.severity, severity];
      setFilters({ ...filters, severity: nextSeverity });
    },
    [filters, setFilters],
  );

  const toggleScanType = useCallback(
    (scanType: ScanType) => {
      const has = filters.scan_type.includes(scanType);
      const nextScanType = has
        ? filters.scan_type.filter((s) => s !== scanType)
        : [...filters.scan_type, scanType];
      setFilters({ ...filters, scan_type: nextScanType });
    },
    [filters, setFilters],
  );

  const clearAll = useCallback(() => {
    setFilters({ file_id: null, scan_type: [], severity: [] });
  }, [setFilters]);

  return { clearAll, filters, setFilters, toggleScanType, toggleSeverity };
}
