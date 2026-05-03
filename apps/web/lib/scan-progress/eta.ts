/**
 * ETA estimation for the live scan progress page (T3.6).
 *
 * Pure helpers — no React, easy to unit test. The progress page feeds in the
 * latencies of recently-finalized scan_files (from the tail-log endpoint) and
 * the count of files that haven't completed yet.
 */

/** Compute the ETA in milliseconds, or `null` if we don't have enough data. */
export function computeEta({
  remaining,
  latencies,
}: {
  remaining: number;
  latencies: ReadonlyArray<number>;
}): number | null {
  if (remaining <= 0) return null;
  if (latencies.length < 3) return null;
  const lastN = latencies.slice(-10);
  const avg = lastN.reduce((sum, x) => sum + x, 0) / lastN.length;
  return Math.round(remaining * avg);
}

/** Format an ETA in milliseconds to a short human label ("12s" / "2m 3s"). */
export function formatEta(etaMs: number): string {
  const totalSeconds = Math.max(0, Math.round(etaMs / 1000));
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds - minutes * 60;
  return `${minutes}m ${seconds}s`;
}
