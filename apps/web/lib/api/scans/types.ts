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
