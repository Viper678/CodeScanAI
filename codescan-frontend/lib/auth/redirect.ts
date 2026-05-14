/** Default landing page for an authenticated user. */
export const APP_HOME_PATH = '/uploads';

/** Path to the sign-in page. */
export const LOGIN_PATH = '/login';

/** Path to the sign-up page. */
export const REGISTER_PATH = '/register';

const AUTH_PATHS: ReadonlySet<string> = new Set([LOGIN_PATH, REGISTER_PATH]);

/**
 * Build the URL to send an unauthenticated user to.
 *
 * Preserves the original path as `?from=<path>` so that, after a successful
 * login, the caller can bounce them back. We deliberately drop query strings
 * and hashes — they may contain transient state and aren't worth restoring.
 */
export function buildLoginRedirect(currentPath: string): string {
  if (!currentPath || AUTH_PATHS.has(currentPath)) {
    return LOGIN_PATH;
  }
  return `${LOGIN_PATH}?from=${encodeURIComponent(currentPath)}`;
}

/**
 * Resolve the post-login destination given an optional `from` query value.
 *
 * Only same-origin absolute paths (starting with `/` and not `//`) are
 * accepted to avoid an open-redirect to another host.
 */
export function resolvePostLoginDestination(from: string | null): string {
  if (from === null || from.length === 0) return APP_HOME_PATH;
  if (!from.startsWith('/')) return APP_HOME_PATH;
  if (from.startsWith('//')) return APP_HOME_PATH;
  if (AUTH_PATHS.has(from)) return APP_HOME_PATH;
  return from;
}
