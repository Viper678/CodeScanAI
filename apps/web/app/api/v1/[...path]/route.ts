/**
 * Runtime API proxy (M7).
 *
 * Forwards every same-origin ``/api/v1/<path>`` request to the api service
 * at ``${INTERNAL_API_URL}/<path>``. Originally implemented as a Next.js
 * ``rewrites()`` entry in ``next.config.mjs``, but Codex flagged that
 * ``rewrites()`` evaluates ``process.env`` at BUILD time and bakes the
 * destination string into ``.next/routes-manifest.json`` — defeating the
 * "one image, runtime-configurable" promise from docs/GCP_MIGRATION.md
 * §D4. App Router route handlers run in the Node.js runtime per request,
 * so ``INTERNAL_API_URL`` is read fresh each time and the same image
 * deploys to UAT / prod / future staging unchanged.
 *
 * The handler is intentionally minimal: forward method, headers, query,
 * and body (as a stream — see ``init.body = req.body``); stream the
 * response body straight back to the browser. The api stays the single
 * source of truth for auth, CSRF, rate limits, errors.
 *
 * SECURITY — client-IP forwarding (Codex P1 round 2 on M7):
 * Inbound ``X-Forwarded-For`` / ``X-Real-IP`` / ``Forwarded`` headers are
 * always stripped before forwarding upstream. We deliberately do NOT
 * inject our own ``X-Forwarded-For`` from ``NextRequest.ip`` because
 * Next.js derives ``.ip`` from the same client-supplied headers we just
 * stripped, so trusting it would let an attacker spoof their IP for the
 * api's per-IP rate limit on /auth/login + /auth/register.
 *
 * Known consequence: under the current shape (no trusted LB in front of
 * web), the api's ``request.client.host`` reflects the web pod's IP
 * rather than the real browser's. The auth IP rate limiter therefore
 * rate-limits per web pod, not per browser. This is a regression vs the
 * pre-M7 direct-browser-to-api shape but the SAFE failure mode (no
 * spoofing) — proper per-client rate limiting needs an upstream LB
 * (Cloud Armor in prod) that strips inbound forwarded headers and sets
 * a trusted one, and a corresponding api-side opt-in. Tracked separately
 * (likely §M8 / Phase B); explicitly out of scope for M7.
 */

import { type NextRequest } from 'next/server';

import { isUnsafeSegment } from '@/lib/api/proxy-segment-guard';

const DEFAULT_INTERNAL_API_URL = 'http://api:8000/api/v1';

/** Headers the catch-all does NOT forward upstream. */
const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
  // ``host`` is set by fetch from the target URL; forwarding the original
  // host header would point fetch at the wrong upstream.
  'host',
  // ``content-length`` is computed by fetch from the body length; forwarding
  // the original (which may differ if the runtime re-encodes) trips strict
  // proxies.
  'content-length',
]);

/** Inbound forwarded-IP headers that we always strip — see the SECURITY
 * note in the module docstring. Never trust client-supplied values for
 * these; Next.js's ``NextRequest.ip`` is itself derived from these so
 * we don't reuse it either. */
const FORWARDED_REQUEST_HEADERS = new Set([
  'x-forwarded-for',
  'x-real-ip',
  'forwarded',
  // The "client hint" cousins — strip too in case anything downstream
  // ever tries to honor them as a substitute.
  'x-forwarded-host',
  'x-forwarded-proto',
]);

function buildTargetUrl(req: NextRequest, pathSegments: string[]): URL {
  const base = (
    process.env.INTERNAL_API_URL ?? DEFAULT_INTERNAL_API_URL
  ).replace(/\/$/, '');
  // ``encodeURIComponent`` per segment ensures any percent-escapes,
  // slashes, or other metacharacters in a segment are preserved as
  // opaque bytes when ``new URL()`` normalizes the path. Combined with
  // the ``isUnsafeSegment`` guard above, this closes the traversal hole
  // codex flagged on round 3.
  const encoded = pathSegments.map(encodeURIComponent).join('/');
  const target = new URL(`${base}/${encoded}`);
  target.search = new URL(req.url).search;
  return target;
}

function forwardHeaders(req: NextRequest): Headers {
  const out = new Headers();
  req.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (HOP_BY_HOP_HEADERS.has(lower)) return;
    // Always strip — see SECURITY note above. We do NOT re-inject an
    // own value because the only source we have (``NextRequest.ip``)
    // is itself derived from these client-controlled headers.
    if (FORWARDED_REQUEST_HEADERS.has(lower)) return;
    out.set(key, value);
  });
  return out;
}

function copyResponseHeaders(upstream: Response): Headers {
  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (HOP_BY_HOP_HEADERS.has(key.toLowerCase())) return;
    if (key.toLowerCase() === 'set-cookie') return; // handled separately
    out.set(key, value);
  });
  // ``getSetCookie`` (Node.js 18+) preserves multiple ``Set-Cookie`` headers
  // as separate entries — joining via ``Headers.get('set-cookie')`` would
  // collapse them into one comma-joined string and break cookie parsing
  // in the browser. Append each cookie individually.
  for (const cookie of upstream.headers.getSetCookie()) {
    out.append('set-cookie', cookie);
  }
  return out;
}

async function proxy(
  req: NextRequest,
  context: { params: { path: string[] } },
): Promise<Response> {
  // Validate BEFORE any URL construction so a traversal attempt never
  // reaches ``new URL()`` (which would normalize ``../`` out of the
  // path and let the request escape the ``/api/v1`` prefix).
  for (const segment of context.params.path) {
    if (isUnsafeSegment(segment)) {
      return new Response('Bad Request', { status: 400 });
    }
  }

  const target = buildTargetUrl(req, context.params.path);
  const headers = forwardHeaders(req);

  // ``duplex: 'half'`` is required by the WHATWG fetch spec when the body
  // is a stream (vs a Buffer / string). Node's ``fetch`` throws otherwise.
  // Codex P2 round 2 on M7: previous shape ``await req.arrayBuffer()``
  // buffered the entire upload (100 MiB cap) inside the web process before
  // forwarding — concurrent uploads would exhaust the 512 MiB pod budget
  // before FastAPI's spool got a chance to run. Streaming ``req.body``
  // straight through keeps web's RSS bounded regardless of payload size;
  // backpressure flows end-to-end from the api spool back to the browser.
  const init: RequestInit & { duplex?: 'half' } = {
    method: req.method,
    headers,
    redirect: 'manual',
  };
  // GET / HEAD requests don't carry a body. Streaming is required for
  // everything else so use ``req.body`` (a ReadableStream) rather than
  // materializing ``arrayBuffer()``.
  if (req.method !== 'GET' && req.method !== 'HEAD' && req.body) {
    init.body = req.body;
    init.duplex = 'half';
  }

  const upstream = await fetch(target.toString(), init);

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: copyResponseHeaders(upstream),
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;

// Force Node.js runtime — Edge runtime has limited ``process.env`` access
// and doesn't support arbitrary outbound fetches the same way.
export const runtime = 'nodejs';
// Force dynamic so the route is never statically optimized — every
// request must hit this handler so ``process.env.INTERNAL_API_URL`` is
// re-read.
export const dynamic = 'force-dynamic';
