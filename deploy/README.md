# `deploy/` — Kubernetes manifests

Plain Kubernetes YAML, hand-written as **starter artifacts** for the
Phase B Helm / Kustomize wrap-up (B7 in `docs/GCP_MIGRATION.md`). The
goal here is to lock in the right manifest *shape* for the migrations
that have to land in code (M5 + M6) — the actual chart / kustomization
that takes these to a real cluster is owned by B7 and is not in this
PR.

## Inventory

```
deploy/
└── k8s/
    ├── migrate-job.yaml         # M5 — alembic upgrade head as a one-shot Job
    ├── worker-deployment.yaml   # M6 — celery worker, replicas=N, no --beat
    └── worker-beat-deployment.yaml  # M6 — celery worker + --beat, replicas=1 strict
```

Eventual full shape (other Deployments land with B7 / B8):

- `api-deployment.yaml` + `api-service.yaml` (B7)
- `web-deployment.yaml` + `web-service.yaml` (B7)
- `vllm-deployment.yaml` + `vllm-service.yaml` (B8 — GPU pool)
- `ingress.yaml` / `BackendConfig` for the HTTPS LB (B6)
- ConfigMap + ESO `ExternalSecret` definitions (B5)

## Deployment ordering

The CI/CD pipeline (B7) runs roughly:

1. Build api / worker / web images, push to Artifact Registry (B4).
2. Apply `migrate-job.yaml` with the new image tag.
3. `kubectl wait --for=condition=complete --timeout=10m job/<name>`.
4. **Only on success**: roll the api / worker / worker-beat / web
   Deployments to the new tag.
5. On failure: abort. The prior Deployments stay on the prior image
   serving the prior schema — no partial-rollout window.

This is exactly what decoupling migrations from the api entrypoint
buys: rollouts that fail closed.

## Why a migrate Job (M5)

Pre-M5 the api container chained `alembic upgrade head &&` into its
entrypoint. That mostly worked, but:

- **Race at scale.** Multi-replica api Deployments all run the
  entrypoint at startup → N parallel `alembic upgrade head` calls
  against one DB. Alembic's advisory-lock fallback handles correctness
  but the pile-up is needless coupling.
- **Version-skew window.** On a rolling update, half the pods are on
  the new image (which expects the new schema), half are on the old
  image (which expects the old schema). If the new pods' entrypoint
  migrates first, the old pods are broken until rollout finishes.
- **Recovery on broken migration.** If a migration fails, every new
  pod CrashLoopBackoffs on startup — there's no clean signal "the
  migration is broken, stop rolling".

The Job pattern lifts the migration out of pod startup so it runs
exactly once per release, and the pipeline can gate the rollout on
its success.

Local docker-compose unchanged: the compose file still chains
`alembic upgrade head` into the api `command:` at compose time
(`docker-compose.yml` + `docker-compose.override.yml`). That's the
dev shape and stays — single-replica, no rolling update, no race.

## Why `worker` vs `worker-beat` are two Deployments (M6)

Celery's `--beat` runs an embedded scheduler in the worker process.
Pre-M6 the single dev compose worker ran `--beat` inline (fine for
one replica). In k8s, scaling that same shape to N replicas means N
schedulers — the daily retention sweep fires N times, the cleanup
metric over-counts by Nx, and any other future scheduled task does
the same.

The structural fix is **Option A** (Helm chart eventually exposes
this as two sub-charts):

| Deployment             | Replicas    | `--beat`? | Strategy        |
|------------------------|-------------|-----------|-----------------|
| `codescan-worker`      | N (HPA)     | no        | RollingUpdate   |
| `codescan-worker-beat` | 1 (strict)  | yes       | Recreate        |

The hard-coded `replicas: 1` and `strategy: Recreate` on
`worker-beat` are load-bearing — scaling past 1 or rolling instead
of recreating reintroduces the exact double-firing bug. Comments in
the file flag this.

If horizontal scheduling ever becomes a need, the spec's Option B
(`celery-redbeat` with a Redis-backed scheduler lock) is the right
shape — not bumping `worker-beat.replicas`.

## What's intentionally NOT here

- **Helm chart / Kustomize bases / `kustomization.yaml`** — Phase B7.
- **Real GCP project IDs / Artifact Registry paths / bucket names** —
  templated by the deploy pipeline. Placeholders only.
- **Network Policies, PDBs, HPAs, ServiceMonitors** — Phase B7 / B9 /
  B10.
- **vLLM Deployment** — Phase B8 (GPU pool).
- **"How to deploy" runbook** — Phase C (cutover).

## References

- `docs/GCP_MIGRATION.md` §M5 — Alembic migrations as a Kubernetes Job.
- `docs/GCP_MIGRATION.md` §M6 — Beat task split (Option A).
- `docs/GCP_MIGRATION.md` Phase B (B3 / B4 / B5 / B7) — infra wiring
  these manifests will plug into.
