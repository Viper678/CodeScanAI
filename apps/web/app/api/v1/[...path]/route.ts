/**
 * Runtime API proxy (M7).
 *
 * Forwards every same-origin ``/api/v1/<path>`` request to the api service
 * at ``${INTERNAL_API_URL}/<path>``. This was originally implemented as a
 * Next.js ``rewrites()`` entry in ``next.config.mjs``, but Codex flagged
 * that ``rewrites()`` evaluates ``process.env`` at BUILD time and bakes
 * the destination string into ``.next/routes-manifest.json`` — defeating
 * the "one image, runtime-configurable" promise from
 * docs/GCP_MIGRATION.md §D4. App Router route handlers run in the Node.js
 * runtime per request, so ``INTERNAL_API_URL`` is read fresh each time
 * and the same image deploys to UAT / prod / future staging unchanged.
 *
 * The handler is intentionally minimal: forward method, headers, query,
 * and body; stream the response body straight back to the browser
 * (preserves the file-viewer endpoint's streaming response). The api
 * stays the single source of truth for auth, CSRF, rate limits, errors.
 *
 * Codex P2 follow-up: ``X-Forwarded-For`` is set so the api's
 * ``_client_ip()`` helper + rate limiter see the real browser IP rather
 * than the web pod's IP. The api side enables uvicorn's ``--proxy-headers``
 * flag to actually trust this header (see ``docker-compose.yml``).
 */

import { type NextRequest } from 'next/server';

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

function buildTargetUrl(req: NextRequest, pathSegments: string[]): URL {
  const base = (
    process.env.INTERNAL_API_URL ?? DEFAULT_INTERNAL_API_URL
  ).replace(/\/$/, '');
  const target = new URL(`${base}/${pathSegments.join('/')}`);
  target.search = new URL(req.url).search;
  return target;
}

function forwardHeaders(req: NextRequest): Headers {
  const out = new Headers();
  req.headers.forEach((value, key) => {
    if (HOP_BY_HOP_HEADERS.has(key.toLowerCase())) return;
    out.set(key, value);
  });
  // Preserve the real client IP for the api's rate limiter + auth audit.
  // ``x-forwarded-for`` may already contain a chain from an upstream LB;
  // append the immediate peer if the request didn't originate inside the
  // pod. ``NextRequest.ip`` is populated by Next.js from the trusted
  // proxy headers in deployment environments (Vercel / nginx / etc.); in
  // docker-compose it's typically undefined, but the api defaults to
  // ``request.client.host`` when the header is absent so the behavior
  // degrades gracefully.
  const existing = req.headers.get('x-forwarded-for');
  const peer = req.ip;
  if (peer) {
    out.set('x-forwarded-for', existing ? `${existing}, ${peer}` : peer);
  } else if (existing) {
    out.set('x-forwarded-for', existing);
  }
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
  const target = buildTargetUrl(req, context.params.path);
  const headers = forwardHeaders(req);

  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: 'manual',
  };
  // GET / HEAD requests don't carry a body; setting body would throw.
  // ``DELETE`` may or may not — pass the body through if present.
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = await req.arrayBuffer();
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
