/** @type {import('next').NextConfig} */
const nextConfig = {
  // ``standalone`` emits a self-contained ``.next/standalone`` tree (server.js
  // plus the minimal node_modules slice it actually imports) so the runner
  // image doesn't need a full ``node_modules`` copy. See ``apps/web/Dockerfile``
  // for the multi-stage build that copies this output into the final layer.
  output: 'standalone',
  async rewrites() {
    // Resolve at request time (not bake time) so a runtime env-var flip
    // is honoured without rebuilding the image — one image deploys to
    // UAT / prod / future staging, only ``INTERNAL_API_URL`` differs.
    // The default keeps docker-compose working out of the box: ``api`` is
    // the service name on the internal compose network. See
    // docs/GCP_MIGRATION.md §M7 + §D4.
    //
    // Source matches the existing API base path (``/api/v1``) so client
    // code can keep calling ``fetch('/api/v1/...')`` unchanged; we don't
    // strip the prefix when forwarding to the api service.
    const target = process.env.INTERNAL_API_URL ?? 'http://api:8000/api/v1';
    return [
      {
        source: '/api/v1/:path*',
        destination: `${target}/:path*`,
      },
    ];
  },
};

export default nextConfig;
