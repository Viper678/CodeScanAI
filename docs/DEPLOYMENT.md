# Deployment

## Local & prod use the same compose file

We use one `docker-compose.yml` with environment-specific overrides:
- `docker-compose.yml` — base
- `docker-compose.override.yml` — local dev (auto-loaded)
- `docker-compose.prod.yml` — production (`docker compose -f docker-compose.yml -f docker-compose.prod.yml up`)

---

## Services

| Service   | Image / build context           | Ports (local)  | Depends on        |
| --------- | ------------------------------- | -------------- | ----------------- |
| `web`     | build `apps/web`                | `3000:3000`    | `api`             |
| `api`     | build `apps/api`                | `8000:8000`    | `postgres`, `redis` |
| `worker`  | build `apps/worker`             | —              | `postgres`, `redis` |
| `postgres`| `postgres:16-alpine`            | `127.0.0.1:5432:5432` (dev only) | — |
| `redis`   | `redis:7-alpine`                | `127.0.0.1:6379:6379` (dev only) | — |
| `proxy`   | `caddy:2-alpine` (prod)         | `80:80, 443:443` | `web`, `api`    |

In **prod**: `postgres` and `redis` ports are NOT exposed to the host — only on the internal docker network. `proxy` terminates TLS and routes `/` to web, `/api` to api.

---

## Volumes

| Volume         | Mount                         | Purpose                          |
| -------------- | ----------------------------- | -------------------------------- |
| `pgdata`       | `postgres:/var/lib/postgresql/data` | DB persistence                |
| `data`         | `api,worker:/data`            | Uploads + extracts (shared rw)   |
| `caddy_data`   | `proxy:/data` (prod)          | TLS certs                        |
| `caddy_config` | `proxy:/config` (prod)        | Caddy state                      |

The `data` volume **must** be shared between `api` and `worker` since api writes uploads and worker reads them. Use a named volume; do not bind-mount in prod.

---

## Healthchecks

```yaml
api:
  healthcheck:
    test: ["CMD", "curl", "-fsS", "http://localhost:8000/readyz"]
    interval: 10s
    timeout: 3s
    retries: 5
    start_period: 20s

worker:
  healthcheck:
    test: ["CMD", "celery", "-A", "worker.celery_app", "inspect", "ping", "-d", "celery@$$HOSTNAME"]
    interval: 30s
    timeout: 5s
    retries: 3
    start_period: 30s

postgres:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
    interval: 5s
    timeout: 3s
    retries: 10

redis:
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 5s
    timeout: 3s
    retries: 10
```

`api` and `worker` declare `depends_on: { postgres: { condition: service_healthy }, redis: { condition: service_healthy } }`.

---

## Migrations

Alembic runs as an init-style command before `api` starts:

```yaml
api:
  command: >
    sh -c "alembic upgrade head &&
           uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS:-2}"
```

For zero-downtime deploys later, split this: a one-shot `migrate` service runs first, then `api` and `worker` start. v1 inline is fine.

---

## Environment variables

See `.env.example` for the complete list. Categories:

- **Auth:** `JWT_SECRET`, `JWT_ACCESS_TTL_MIN`, `JWT_REFRESH_TTL_DAYS`
- **DB:** `DATABASE_URL`, `POSTGRES_USER/PASSWORD/DB`
- **Redis:** `REDIS_URL`
- **Storage:** `DATA_DIR` (default `/data`)
- **LLM:** `GOOGLE_AI_API_KEY`, `GEMMA_MODEL` (`gemma-4-31b-it`), `LLM_PARALLELISM`, `LLM_MAX_TOKENS_INPUT`
- **Limits:** `MAX_UPLOAD_SIZE_MB`, `MAX_LOOSE_FILES`, `MAX_FILES_PER_SCAN`, `MAX_SCAN_FILE_SIZE_MB`, `RETENTION_DAYS`
- **Rate limits:** `RATE_LIMIT_LOGIN`, `RATE_LIMIT_UPLOAD`, `RATE_LIMIT_SCAN`
- **CORS / hosts:** `ALLOWED_ORIGINS`, `TRUSTED_HOSTS`
- **Web:** `NEXT_PUBLIC_API_BASE_URL`

JWT_SECRET in prod must come from a secrets manager, not the `.env` file. The compose stack reads it from env directly so the deployment platform (e.g. ECS / Cloud Run / k8s) can inject it.

---

## Resource sizing (starting points)

| Service | CPU | RAM | Notes |
| ------- | --- | --- | ----- |
| api     | 1   | 512MB | 2 uvicorn workers per CPU |
| worker  | 2   | 2GB | LLM calls hold connections; bump if `LLM_PARALLELISM` raised |
| postgres| 1   | 1GB | Tune shared_buffers if scans grow |
| redis   | 0.5 | 256MB | |
| web     | 0.5 | 256MB | Static-ish |

---

## Backups

- Postgres: nightly `pg_dump` (compressed) to object storage. 30-day retention.
- `data` volume: not strictly backed up — uploads are user-supplied and re-uploadable. Findings live in Postgres.

---

## Observability (post-v1, but plan now)

- Structured logs to stdout → log aggregator (Loki / CloudWatch / etc.).
- Metrics: Prometheus exporter on api & worker (`/metrics`, internal-only).
- Traces: OTel SDK behind a feature flag, exporter URL via env.

---

## Deploy targets considered

- **Single VM** (cheapest, fine for v1): one Docker host running compose. Backups via cron.
- **Cloud Run / ECS Fargate**: api + worker as separate services; Postgres + Redis managed; persistent uploads on a network FS or migrate to object storage first.
- **Kubernetes**: overkill for v1, but the layout already maps cleanly (Deployment per service, PVC for uploads, CronJob for cleanup).

Pick one based on team competency. None are in `docker-compose.yml` initially.
