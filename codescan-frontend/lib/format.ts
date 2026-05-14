/**
 * Tiny formatting helpers shared across surfaces.
 *
 * Lifted out of `components/upload/upload-step.tsx` so list rows on the
 * `/uploads` and `/scans` pages can format byte sizes the same way the
 * upload wizard does.
 */

/** Format a byte count as a short human-readable string (e.g. `1.2 MB`). */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  return `${(mb / 1024).toFixed(2)} GB`;
}

const SHORT_DATE_FORMATTER = new Intl.DateTimeFormat(undefined, {
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  month: 'short',
  year: 'numeric',
});

/**
 * Render an ISO timestamp as a short, locale-aware date+time, e.g.
 * "May 3, 2026, 14:32". Returns the empty string for null/invalid input
 * so callers don't have to null-check before slotting it into JSX.
 */
export function formatShortDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const ts = new Date(iso);
  if (Number.isNaN(ts.getTime())) return '';
  return SHORT_DATE_FORMATTER.format(ts);
}
