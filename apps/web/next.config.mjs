/** @type {import('next').NextConfig} */
const nextConfig = {
  // ``standalone`` emits a self-contained ``.next/standalone`` tree (server.js
  // plus the minimal node_modules slice it actually imports) so the runner
  // image doesn't need a full ``node_modules`` copy. See ``apps/web/Dockerfile``
  // for the multi-stage build that copies this output into the final layer.
  output: 'standalone',
  // NOTE on the ``rewrites()`` shape: Next.js evaluates ``rewrites()`` at
  // BUILD time and bakes the resulting destination strings into
  // ``.next/routes-manifest.json``. That defeats the "one image, runtime-
  // configurable" promise from docs/GCP_MIGRATION.md §D4 — a value of
  // ``process.env.INTERNAL_API_URL`` read here is just whatever was set
  // during ``docker build``. The catch-all route handler at
  // ``apps/web/app/api/v1/[...path]/route.ts`` runs in the Node.js
  // runtime per request and reads ``INTERNAL_API_URL`` fresh each time;
  // that's where the runtime-configurable proxy actually lives. Codex
  // P1 on M7.
};

export default nextConfig;
