# Vela Helm Chart

Packages the Vela MLOps platform (backend API, model-service, PostgreSQL,
MinIO, Redis, and the RBAC the backend needs to manage model Deployments) as
a single Helm release. This chart mirrors the manifests in `k8s/*.yaml` -
it does not change any application behavior, it just makes the deployment
configurable and repeatable.

## What gets installed

| Resource | Purpose |
|---|---|
| `backend-app` Deployment + Service (+ external LoadBalancer) | Vela API / dashboard |
| `model-service` Deployment + Service (+ optional ServiceMonitor) | model serving + metrics |
| `postgres` Deployment + PVC + Service (skipped if `production.externalDatabase.enabled`) | primary datastore |
| `minio` Deployment + PVC + Service (skipped if `production.externalMinio.enabled`) | object storage for model artifacts |
| `redis` Deployment + Service | drift-detection state |
| `postgres-secret`, `minio-secret`, `groq-secret`, `gemini-secret`, `github-secret`, `ghcr-secret` | credentials, consumed via `envFrom`/`secretKeyRef` |
| `ClusterRole` / `ClusterRoleBinding` | lets the backend service account create/manage Deployments, Services, ConfigMaps, PVCs, and Jobs for deployed models |
| `Ingress` (optional, disabled by default) | host-based routing to `backend-app` in place of/alongside the LoadBalancer service |
| `PodDisruptionBudget` for backend-app/model-service (optional, disabled by default) | see [PRODUCTION.md](PRODUCTION.md) |

## Prerequisites

- Kubernetes 1.24+
- Helm 3.8+
- A `ReadWriteOnce`-capable StorageClass (default one is fine) for the Postgres and MinIO PVCs
- A GitHub PAT with `read:packages` scope to pull images from GHCR (`ghcr.io/hassanfasseh/vela/*`), unless you've already created the `ghcr-secret` yourself

## Installing

The chart requires four values with no safe default - the database password,
the MinIO root password, and (in practice) at least one LLM key so drift
explanations work. Pull-secret credentials are also required unless you set
`registry.createPullSecret=false` and provide `ghcr-secret` out of band.

```bash
helm install vela ./helm/vela \
  --set secrets.groqApiKey=gsk_... \
  --set secrets.githubToken=ghp_... \
  --set database.password=secure_password \
  --set minio.rootPassword=secure_password \
  --set registry.ghcr.username=<your-github-username> \
  --set registry.ghcr.password=<your-ghcr-pat>
```

Or with a values file (recommended for anything beyond a quick test -
avoids secrets ending up in shell history):

```bash
helm install vela ./helm/vela -f my-vela-values.yaml
```

```yaml
# my-vela-values.yaml
database:
  password: secure_password
minio:
  rootPassword: secure_password
secrets:
  groqApiKey: gsk_...
  geminiApiKey: ...
  githubToken: ghp_...
  githubRepo: HassanFasseh/vela
registry:
  ghcr:
    username: HassanFasseh
    password: ghp_...
```

Check rollout:

```bash
kubectl get pods -w
```

## Configuration reference

All values live in [`values.yaml`](values.yaml). The main groups:

### Registry (`registry.*`)
- `registry.repository` - image repo prefix, e.g. `ghcr.io/hassanfasseh/vela`
- `registry.createPullSecret` - set `false` to skip creating `ghcr-secret` (use if it already exists in-cluster)
- `registry.ghcr.username` / `registry.ghcr.password` - GHCR credentials used to build the `ghcr-secret` dockerconfigjson. The PAT expires (~90 days) - re-run `helm upgrade` with a fresh one when it does.

### Backend (`backend.*`)
- `backend.replicaCount`, `backend.image.tag`, `backend.resources`
- `backend.service.*` - internal ClusterIP service
- `backend.externalService.*` - external LoadBalancer (set `enabled: false` if you're fronting with your own Ingress/LoadBalancer instead); `backend.externalService.annotations` is where cloud-provider annotations go, e.g. the OCI load balancer subnet.

### Model service (`modelService.*`)
- `modelService.replicaCount`, `modelService.image.tag`, `modelService.resources`
- `modelService.serviceMonitor.enabled` - set `true` to scrape `/metrics` via the Prometheus Operator (requires its CRDs installed)

### Database (`database.*`)
- `database.name`, `database.user`, `database.password` (required), `database.storageSize`, `database.storageClassName`
- `database.urlOverride` - set this instead if you want to point at an external Postgres rather than the in-cluster one; when set it replaces the derived `DATABASE_URL`

### MinIO (`minio.*`)
- `minio.rootUser`, `minio.rootPassword` (required), `minio.storageSize`, `minio.storageClassName`, `minio.endpoint`

### Secrets / integrations (`secrets.*`)
- `secrets.groqApiKey`, `secrets.geminiApiKey` - LLM providers used for drift explanations (`backend/app/services/summary.py`); set at least one
- `secrets.githubToken`, `secrets.githubRepo` - used to open drift issues / trigger the deploy workflow
- `secrets.backend` - `kubernetes` (default, above), `vault`, or `external-secrets` - switches where all of this actually comes from. See **[SECRET_MANAGEMENT.md](SECRET_MANAGEMENT.md)** for setting up Vault or the External Secrets Operator, rotation, and migrating between backends.

### RBAC (`rbac.*`)
- `rbac.create` - set `false` if you manage the ClusterRole/Binding yourself
- `rbac.serviceAccountName` - defaults to `default`; set to a custom name to have the chart create a dedicated ServiceAccount instead of granting the namespace's `default` account

### Ingress (`ingress.*`)
Off by default (the reference deployment uses the `backend-external` LoadBalancer). Enable it to route by hostname instead:

```yaml
ingress:
  enabled: true
  className: nginx
  host: vela.yourcompany.com
  tls:
    enabled: true
    secretName: vela-tls
```

### Resource limits / storage / replicas
Every Deployment's `resources.requests`/`resources.limits` and every PVC's storage size are set under that component's key (`backend.resources`, `database.storageSize`, etc.) - see `values.yaml` for the full set of defaults, which match what's running in `k8s/*.yaml` today.

## Upgrading

```bash
helm upgrade vela ./helm/vela -f my-vela-values.yaml
```

Helm only re-applies what changed. Notes:

- **Rotating the GHCR PAT**: `helm upgrade ... --set registry.ghcr.password=<new-pat>` regenerates `ghcr-secret`; existing pods keep running on their already-pulled images, new pulls use the new credential.
- **Rotating LLM/GitHub keys**: same pattern - `--set secrets.groqApiKey=...` etc. The backend Deployment does not automatically restart on a Secret change; run `kubectl rollout restart deployment/backend-app` afterwards to pick up new env values.
- **Changing image tags**: `--set backend.image.tag=...` / `--set modelService.image.tag=...` triggers a normal rolling update.
- **Database/MinIO password changes**: only change these if you also update the underlying data (Postgres/MinIO won't retroactively re-auth existing volumes with a new password baked in by the container's first-boot init) - safest done by setting the new password before first install rather than on an existing PVC.

## Production deployment

The defaults above target a single-node cluster. For a multi-node
production setup - anti-affinity, PodDisruptionBudgets, Guaranteed-QoS
resource limits, external managed Postgres/S3 instead of the in-cluster
single-replica ones, health checks, and Horizontal Pod Autoscaler setup for
the backend - see **[PRODUCTION.md](PRODUCTION.md)**, including full
example `values.yaml` files for a 3-node cluster on AWS EKS and Azure AKS.

## Uninstalling

```bash
helm uninstall vela
```

This does **not** delete the `postgres-pvc` / `minio-pvc` PersistentVolumeClaims (Helm doesn't delete PVCs on uninstall by default), so re-installing the release will reattach existing data. Delete them manually if you want a clean slate:

```bash
kubectl delete pvc postgres-pvc minio-pvc
```

## Notes

- This chart intentionally does not touch application code - it packages the same containers and config that `k8s/*.yaml` already deploys.
- The `ClusterRole`/`ClusterRoleBinding` grant broad create/update/delete on Deployments, Services, ConfigMaps, PVCs, and Jobs - that's what lets the backend spin up per-model `model-runner` Deployments from the dashboard. Scope it down further if you're running Vela in a shared cluster.
- Multi-arch model-runner images (`model-runner`, `model-runner:custom-{name}`) are built and pushed by CI, not by this chart - the chart only manages the long-running platform services.
