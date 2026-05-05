FROM node:20-alpine

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

EXPOSE 3000
CMD ["pnpm", "dev"]
