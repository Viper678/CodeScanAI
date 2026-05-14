# =====================================================================
# Multi-stage Next.js standalone production image (M7).
#
# Stage 1 (``builder``) installs deps + runs ``pnpm build`` against the
# ``output: 'standalone'`` Next.js config. The build emits a self-contained
# ``.next/standalone`` tree (``server.js`` + just the slice of node_modules
# it actually imports) so the runner stage doesn't need a full
# ``node_modules`` copy.
#
# Stage 2 (``runner``) copies the standalone tree + static + public into a
# clean ``node:20-alpine`` layer and runs ``node server.js``. No pnpm /
# install step at runtime; the image is the deliverable.
#
# Why same image for dev: the docker-compose dev override
# (``docker-compose.override.yml``) swaps ``command:`` back to ``pnpm dev``
# and mounts ``./apps/web`` over ``/app`` so hot-reload works without
# rebuilding. The builder stage's source copy is therefore harmless in
# dev — the bind mount shadows it.
#
# Per docs/GCP_MIGRATION.md §D4: API host is read at REQUEST time via
# Next.js ``rewrites()`` reading ``INTERNAL_API_URL`` — NOT a build-arg.
# One image deploys to UAT / prod / future staging unchanged.
# =====================================================================

# ---- Stage 1: builder ------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

# Verify install actually wrote the deps to disk. pnpm-on-alpine has twice
# silently dropped packages (T3.5 @tanstack, T4.3 @uiw/@codemirror) while
# logging "+ <pkg>" success — the bad image then 500s at runtime with
# "Module not found". Pin a handful of canonical top-level deps; if any
# went missing during install, fail the build now instead of shipping a
# broken image. Update the list when adding a critical new top-level dep.
RUN set -e; \
    for pkg in next react @base-ui/react @tanstack/react-query @uiw/react-codemirror @codemirror/view; do \
      if [ ! -d "node_modules/$pkg" ]; then \
        echo "FATAL: pnpm install incomplete — node_modules/$pkg is missing"; \
        echo "       (lockfile says $(grep -c "^  '$pkg':" pnpm-lock.yaml || echo 0) entries; see feedback_docker_web_deps memory note)"; \
        exit 1; \
      fi; \
    done

COPY . .

# ``next build`` honours ``output: 'standalone'`` from next.config.mjs and
# writes to ``.next/standalone`` (server tree) + ``.next/static`` (hashed
# assets) + ``public`` (unchanged).
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build


# ---- Stage 2: runner -------------------------------------------------
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
# Bind Next.js to all interfaces — the container's network namespace
# is sandboxed so 0.0.0.0 only exposes the port docker-compose / k8s
# publishes anyway.
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

# Run as a non-root user (``node`` UID 1000 ships with the official
# image). The builder stage already wrote the standalone tree as root,
# so we ``--chown`` while copying rather than chmod -R after the fact.
# ``public/`` and ``.next/static`` are static assets served by the
# standalone server; the rest of the runtime lives under
# ``.next/standalone`` (server.js + its minimal node_modules slice).
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node

EXPOSE 3000

CMD ["node", "server.js"]
