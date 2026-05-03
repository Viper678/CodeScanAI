/**
 * Scan-related types mirroring the contract in docs/API.md §Scans and the
 * Pydantic schemas in apps/api/app/schemas/scan.py.
 *
 * The frontend never writes these — the API is the source of truth — but we
 * keep the shapes here so callers (components, hooks) can stay typed without
 * importing the generated OpenAPI types until those land.
 */

export type ScanType = 'security' | 'bugs' | 'keywords';

export type ScanStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type KeywordsConfig = {
  items: string[];
  case_sensitive: boolean;
  regex: boolean;
};

export type ScanCreateRequest = {
  upload_id: string;
  name?: string | null;
  scan_types: ScanType[];
  file_ids: string[];
  keywords?: KeywordsConfig;
  model_settings?: Record<string, unknown>;
};

export type ScanCreateResponse = {
  id: string;
  status: ScanStatus;
  progress_done: number;
  progress_total: number;
};

/** Severity literal — mirrors `apps/api/app/schemas/scan.py`. */
export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

/** Per-file lifecycle status for the recent-files tail. */
export type ScanFileStatus =
  | 'pending'
  | 'running'
  | 'done'
  | 'failed'
  | 'skipped';

/**
 * Aggregate counters surfaced on `GET /scans/{id}`. The API uses
 * `Partial<Record<...>>` shape — keys for severities/types with zero rows are
 * omitted, so callers must default to 0 when a key is missing.
 */
export type ScanSummary = {
  by_severity: Partial<Record<Severity, number>>;
  by_type: Partial<Record<ScanType, number>>;
};

/** Full scan row returned by `GET /scans/{id}`. */
export type ScanDetail = {
  id: string;
  name: string | null;
  upload_id: string;
  scan_types: ScanType[];
  status: ScanStatus;
  progress_done: number;
  progress_total: number;
  started_at: string | null;
  finished_at: string | null;
  summary: ScanSummary;
  /** Surfaced when status='failed'. */
  error?: string | null;
};

/** One row in the recent-files tail. */
export type ScanFileItem = {
  id: string;
  file_id: string;
  path: string;
  status: ScanFileStatus;
  error: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  started_at: string | null;
  finished_at: string | null;
};

/** Response body for `GET /scans/{id}/files`. */
export type ScanFilesResponse = {
  items: ScanFileItem[];
};
