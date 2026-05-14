/**
 * Path-segment validation for the runtime API proxy
 * (codescan-frontend/app/api/v1/[...path]/route.ts).
 *
 * Lives outside the route directory because Next.js's App Router enforces
 * that route.ts files only export HTTP method handlers + a fixed set of
 * config flags (``runtime``, ``dynamic``, etc.) — exporting helper
 * functions there fails the build's type check.
 */

/** Reject any path segment that resolves to ``.`` / ``..`` / empty after
 * recursively decoding percent-escapes. Without this guard, encoded
 * traversal sequences (``%2e%2e`` / ``%252e%252e``) would let the URL
 * constructor normalize the path and escape the ``/api/v1`` prefix,
 * exposing api routes like ``/readyz`` / ``/healthz``. Codex P2 round 3
 * on M7.
 *
 * The recursion handles multi-layer encoding (``%252e%252e`` → ``%2e%2e``
 * → ``..``). 8 iterations is far more than any legitimate path needs.
 */
export function isUnsafeSegment(segment: string): boolean {
  let decoded = segment;
  for (let i = 0; i < 8; i++) {
    let next: string;
    try {
      next = decodeURIComponent(decoded);
    } catch {
      // Malformed percent encoding — reject rather than letting fetch
      // or the api try to interpret it.
      return true;
    }
    if (next === decoded) break;
    decoded = next;
  }
  return decoded === '.' || decoded === '..' || decoded === '';
}
