/**
 * Upload-related types mirroring the contract in docs/API.md §Uploads.
 *
 * The frontend never writes these — the API is the source of truth — but we
 * keep the shapes here so callers (components, hooks) can stay typed without
 * importing the generated OpenAPI types until those land.
 */

/** Lifecycle states an upload row can be in. */
export type UploadStatus = 'received' | 'extracting' | 'ready' | 'failed';

/** What kind of payload was sent. */
export type UploadKind = 'zip' | 'loose';

/**
 * Initial response from `POST /uploads`. The server has accepted the bytes
 * and queued extraction. Subsequent fields land via `GET /uploads/{id}`.
 */
export type CreateUploadResponse = {
  id: string;
  status: UploadStatus;
  kind: UploadKind;
  original_name: string;
  size_bytes: number;
};

/** Full upload row as returned by `GET /uploads/{id}`. */
export type Upload = {
  id: string;
  status: UploadStatus;
  kind: UploadKind;
  original_name: string;
  size_bytes: number;
  file_count: number | null;
  scannable_count: number | null;
  created_at: string;
  error: string | null;
};
