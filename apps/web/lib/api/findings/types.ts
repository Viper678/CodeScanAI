/**
 * Finding-related types mirroring the contract in docs/API.md §Findings and
 * the Pydantic schemas behind `GET /scans/{id}/findings` (T4.1, PR #27).
 *
 * The frontend never writes these — the API is the source of truth — but we
 * keep the shapes here so callers (components, hooks) stay typed without
 * importing the generated OpenAPI types until those land.
 */
import type { ScanType, Severity } from '@/lib/api/scans/types';

/** File reference embedded in each finding row. */
export type FindingFile = {
  id: string;
  path: string;
};

/** Single finding row from `GET /scans/{id}/findings`. */
export type Finding = {
  id: string;
  scan_type: ScanType;
  severity: Severity;
  title: string;
  message: string;
  recommendation: string | null;
  file: FindingFile;
  line_start: number | null;
  line_end: number | null;
  snippet: string | null;
  rule_id: string | null;
  confidence: number | null;
};

/** Cursor-paginated response for `GET /scans/{id}/findings`. */
export type FindingsListResponse = {
  items: Finding[];
  next_cursor: string | null;
  total: number;
};

/**
 * Normalized filter state used by the panel + URL sync. Severity / scan-type
 * are multi-select, file_id is single-select. Empty arrays mean "no filter
 * for this dimension" — the client serializer drops the param entirely so
 * the server returns the unfiltered set.
 */
export type FindingsFilters = {
  severity: Severity[];
  scan_type: ScanType[];
  file_id: string | null;
};

/** Export format query param for `GET /scans/{id}/export?fmt=`. */
export type ExportFormat = 'json' | 'csv';
