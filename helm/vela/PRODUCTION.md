# Production / multi-node deployment

The chart's defaults target a single-node cluster (matches the reference
OKE deployment in `k8s/*.yaml`). This guide covers what changes - and, just
as importantly, what *doesn't* automatically change - once you're spreading
Vela across multiple nodes.

## Minimum recommended specs

| | Minimum | Recommended |
|---|---|---|
| Nodes | 3 | 3+ (odd number if you also run etcd/control-plane workloads on the same nodes) |
| Per node | 4 vCPU / 16 GB RAM | 4 vCPU / 16 GB RAM |
| Storage | Block storage (EBS/Azure Disk/PD) for Postgres+MinIO if kept in-cluster | Managed database + S3-compatible object storage instead (see below) |

Why 3 nodes specifically: it's the minimum that lets `podAntiAffinity` with
`mode: required` actually schedule more than one replica of a component (2
nodes means 2 replicas max before pods go `Pending`), and it's the minimum
most managed Kubernetes control planes (EKS, AKS, GKE) recommend anyway for
their own etcd/control-plane resilience if you're not using a fully managed
control plane tier. 4 vCPU / 16 GB per node covers backend-app +
model-service + Redis with headroom for the per-model `model-runner`
Deployments the backend spins up on demand (each requesting up to 2 GB/500m
by default - see `k8s/model-deployment.yaml`/`model-service-2.yaml`).

## Why Postgres and MinIO need special handling in multi-node

This chart runs Postgres and MinIO as single-replica Deployments backed by
`ReadWriteOnce` PVCs (see `templates/postgres-deployment.yaml`/
`minio-deployment.yaml`). That's a deliberate simplification, not an
oversight - and it's worth understanding why before reaching for RWX
volumes as "the multi-node fix":

- **Postgres can't have multiple writers against shared storage, full
  stop**, regardless of the volume's access mode. `ReadWriteMany` (NFS,
  EFS, Azure Files, CephFS) lets multiple *pods* mount the same volume
  concurrently, but PostgreSQL's on-disk format assumes a single process
  owns it - two `postgres` processes writing to the same data directory
  corrupts it. RWX buys you nothing for Postgres HA; real Postgres HA needs
  streaming replication between *separate* data directories (e.g.
  Patroni, CloudNativePG), which this chart doesn't implement.
- **MinIO's real distributed/HA mode needs multiple independent disks
  across nodes**, not one shared volume - its erasure-coding scheme
  specifically requires each node to have its own local storage. Pointing
  several MinIO replicas at one shared RWX volume doesn't give you MinIO's
  actual HA story, just several processes fighting over one disk (better
  than Postgres's case in that MinIO tolerates it more gracefully, but
  still not what "highly available object storage" means).
- **A single-replica Postgres/MinIO pod on RWO storage isn't broken by a
  multi-node cluster** - Kubernetes reattaches the PVC to whatever node the
  pod gets rescheduled onto (with a brief detach/reattach delay on most
  cloud block storage). It's just still a single point of failure and does
  nothing to help you scale reads/writes, no matter how many nodes the rest
  of Vela spreads across.

**Bottom line: RWX volumes solve a scheduling-flexibility problem, not an
HA problem, for either service.** If you need actual HA for the database or
object storage, that has to come from outside this chart.

## Recommended: external managed services

For a real multi-node production deployment, point `production.externalDatabase`
at a managed PostgreSQL instance (AWS RDS, Azure Database for PostgreSQL,
GCP Cloud SQL, ...) and `production.externalMinio` at S3-compatible object
storage (AWS S3, Azure Blob with an S3-compatible gateway, GCS with
interoperability mode, or a separately-run MinIO cluster with its own local
disks per node) instead of the in-cluster Postgres/MinIO this chart ships
by default:

```yaml
production:
  externalDatabase:
    enabled: true
    host: vela.xxxxxxxxxx.us-east-1.rds.amazonaws.com
    port: 5432
    name: aodp
    existingSecret: vela-db-credentials # you create this Secret; needs a POSTGRES_PASSWORD key

  externalMinio:
    enabled: true
    endpoint: vela-artifacts.s3.us-east-1.amazonaws.com
    existingSecret: vela-s3-credentials # you create this Secret; needs MINIO_ROOT_USER + MINIO_ROOT_PASSWORD keys
```

Create the two Secrets yourself before installing (they're deliberately
*not* something Helm generates for you, since the whole point is that these
credentials live outside this chart's blast radius):

```bash
kubectl create secret generic vela-db-credentials \
  --from-literal=POSTGRES_PASSWORD='<your RDS password>'

kubectl create secret generic vela-s3-credentials \
  --from-literal=MINIO_ROOT_USER='<your AWS access key ID>' \
  --from-literal=MINIO_ROOT_PASSWORD='<your AWS secret access key>'
```

(The key names (`MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`) are historical -
they're literally what backend-app's MinIO client env vars are named
regardless of whether the actual endpoint is MinIO or S3 itself.)

With both enabled, this chart stops rendering the in-cluster
`postgres`/`minio` Deployment, PVC, Service, and Secret entirely (see
`templates/postgres-deployment.yaml`/`minio-deployment.yaml` - there's no
point running an unconnected pod), and backend-app's `DATABASE_URL`/MinIO
client env vars are built from the host/endpoint above plus the password(s)
in your Secret. `database.password`/`minio.rootPassword` in `values.yaml`
become irrelevant in this mode - nothing reads them.

If you're using `secrets.backend: vault` (see `SECRET_MANAGEMENT.md`), this
mode isn't wired into the Vault-injection path - put `DATABASE_URL` and the
MinIO client credentials directly into your Vault KV entry instead (Vault
mode already supports arbitrary keys at `secrets.vault.path`).

## Anti-affinity configuration

```yaml
production:
  podAntiAffinity:
    backend:
      enabled: true # default
      mode: preferred # or "required"
    modelService:
      enabled: true # default
      mode: preferred
```

Both default **on**, in `preferred` mode. That's intentionally a safe
default even on a single-node cluster: `preferredDuringSchedulingIgnoredDuringExecution`
is a soft rule - the scheduler tries to place replicas on different nodes
but happily co-locates them if it can't (e.g. there's only one node). It
becomes real protection the moment you have more than one node, with zero
risk of pods going `Pending` on a small cluster.

Switch to `mode: required` (`requiredDuringSchedulingIgnoredDuringExecution`)
once you're confident you'll always have at least as many schedulable nodes
as replicas - it's a hard rule: the scheduler refuses to place two replicas
of the same component on the same node, full stop, and a replica with
nowhere left to go stays `Pending` instead of silently co-locating. With 3
nodes, `backend.replicaCount: 3` + `mode: required` guarantees each replica
lands on its own node; `replicaCount: 4` with only 3 nodes would leave one
`Pending` forever.

## PodDisruptionBudget

```yaml
production:
  podDisruptionBudget:
    backend:
      enabled: true
      minAvailable: 1
    modelService:
      enabled: true
      minAvailable: 1
```

Off by default. A PDB tells Kubernetes the minimum number of replicas that
must stay up during a *voluntary* disruption - a node drain for a cluster
upgrade, `kubectl drain`, cluster-autoscaler consolidating nodes - as
opposed to an involuntary one (a node crashing), which no PDB can prevent.

**Only turn this on once `replicaCount` is at least `minAvailable + 1`.**
With the default `backend.replicaCount: 1` and `minAvailable: 1`, a PDB
would forbid evicting the *only* replica at all - which doesn't protect
availability, it just blocks node drains from completing until someone
manually deletes the pod. Pair `minAvailable: 1` with `replicaCount: 2` (or
`minAvailable: 2` with `replicaCount: 3`, etc.) so there's always a spare
replica to move first.

## Resource limits

Two related settings:

- **`backend.resources`/`modelService.resources`** (existing, unchanged) -
  the requests/limits split. Requests reserve capacity for scheduling;
  limits cap actual usage.
- **`production.multiNode.enabled`** - when `true`, both Deployments render
  with `requests` forced equal to `limits` instead of the split above (only
  `.limits` is read; `.requests` is ignored in this mode).

The reason: Kubernetes assigns a pod's QoS class from its
requests/limits relationship - `requests == limits` on every container is
**Guaranteed**, the highest class, evicted last under node memory pressure
and give the most predictable CPU behavior on a busy node.
`requests < limits` (the single-node default) is **Burstable** - fine on a
node backend-app has to itself, but on a genuinely multi-node/multi-tenant
cluster where the scheduler is packing several workloads onto shared nodes,
Burstable pods are the first things evicted when a node runs short, which
is exactly the failure mode multi-node is supposed to reduce. Recommended
production baseline, sized for the 4 vCPU / 16 GB nodes above:

```yaml
backend:
  resources:
    limits:
      memory: 1Gi
      cpu: 500m
modelService:
  resources:
    limits:
      memory: 2Gi
      cpu: 1000m
production:
  multiNode:
    enabled: true
```

(`.requests` under each can stay whatever they were - they're not read in
this mode, but leaving them isn't harmful either.)

## Health checks and readiness probes

Off by default (existing installs get no pod-spec change on upgrade unless
you opt in):

```yaml
production:
  healthChecks:
    backend:
      enabled: true
      path: /
    modelService:
      enabled: true
      path: /health
```

model-service has a real `/health` endpoint (`model-service/main.py`) that
also reports Redis connectivity - a genuine readiness signal. backend-app
doesn't have a dedicated health endpoint, so `/` (the landing page) is used
instead: it's a valid **liveness** check (the process is up and serving
HTTP) but not a true **readiness** check, since it doesn't verify
backend-app can actually reach Postgres/MinIO. If you need real dependency
checking for backend-app specifically, that requires adding a proper
`/health` endpoint to the application (out of scope for this chart, which
only packages the existing app).

`initialDelaySeconds`/`periodSeconds`/`timeoutSeconds`/`failureThreshold`
are all configurable per-component under the same block - defaults are
generous (10–15s initial delay) to avoid probe failures during normal
FastAPI/uvicorn startup.

## Horizontal Pod Autoscaler (backend)

This chart doesn't render an HPA - set it up as a standalone manifest
alongside the release. Two things to configure on the chart side first:

1. **Set real resource requests** - HPA's default CPU-utilization metric is
   a percentage *of the request*, so `backend.resources.requests.cpu` has
   to be meaningful (the defaults already set `80m`; size it to your actual
   steady-state usage before turning autoscaling on).
2. **Set `production.autoscaling.backend.enabled: true`.** This stops the
   Deployment template from setting `spec.replicas` at all. Without it,
   every `helm upgrade` resets replica count back to `backend.replicaCount`
   - fighting the HPA, which is the single most common "why does my HPA
   keep getting reset" issue with Helm-managed Deployments in general.

```yaml
backend:
  resources:
    requests:
      cpu: 200m
      memory: 512Mi
production:
  autoscaling:
    backend:
      enabled: true
```

```bash
helm upgrade vela ./helm/vela -f production-values.yaml
```

Then apply the HPA itself (requires the [metrics-server](https://github.com/kubernetes-sigs/metrics-server)
add-on - bundled by default on EKS/AKS/GKE, otherwise install it
separately):

```yaml
# hpa-backend.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: backend-app
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: backend-app
  minReplicas: 2
  maxReplicas: 6
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300 # avoid flapping down right after a scale-up
```

```bash
kubectl apply -f hpa-backend.yaml
kubectl get hpa backend-app -w
```

To go back to Helm-managed replicas: `kubectl delete hpa backend-app`, then
`helm upgrade` with `production.autoscaling.backend.enabled=false` (and set
`backend.replicaCount` to whatever you want it pinned at).

## Example: 3-node cluster on AWS EKS

```yaml
# production-values-eks.yaml
backend:
  replicaCount: 3
  image:
    tag: "<pinned-sha-or-release-tag>"
  resources:
    limits:
      memory: 1Gi
      cpu: 500m
  externalService:
    annotations:
      service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
      service.beta.kubernetes.io/aws-load-balancer-scheme: "internet-facing"

modelService:
  replicaCount: 2
  resources:
    limits:
      memory: 2Gi
      cpu: 1000m
  service:
    annotations:
      service.beta.kubernetes.io/aws-load-balancer-type: "nlb"

production:
  multiNode:
    enabled: true
  podAntiAffinity:
    backend:
      enabled: true
      mode: required
    modelService:
      enabled: true
      mode: required
  podDisruptionBudget:
    backend:
      enabled: true
      minAvailable: 2
    modelService:
      enabled: true
      minAvailable: 1
  externalDatabase:
    enabled: true
    host: vela.xxxxxxxxxx.us-east-1.rds.amazonaws.com
    port: 5432
    name: aodp
    existingSecret: vela-db-credentials
  externalMinio:
    enabled: true
    endpoint: vela-artifacts.s3.us-east-1.amazonaws.com
    existingSecret: vela-s3-credentials
  healthChecks:
    backend:
      enabled: true
    modelService:
      enabled: true
  autoscaling:
    backend:
      enabled: true

# Create vela-db-credentials / vela-s3-credentials Secrets (see above)
# before installing, and an HPA (see above) after.
```

## Example: 3-node cluster on Azure AKS

Same shape - the differences are the load-balancer annotations and the
managed-database naming:

```yaml
# production-values-aks.yaml
backend:
  replicaCount: 3
  image:
    tag: "<pinned-sha-or-release-tag>"
  resources:
    limits:
      memory: 1Gi
      cpu: 500m
  externalService:
    annotations:
      service.beta.kubernetes.io/azure-load-balancer-internal: "false"

modelService:
  replicaCount: 2
  resources:
    limits:
      memory: 2Gi
      cpu: 1000m

production:
  multiNode:
    enabled: true
  podAntiAffinity:
    backend:
      enabled: true
      mode: required
    modelService:
      enabled: true
      mode: required
  podDisruptionBudget:
    backend:
      enabled: true
      minAvailable: 2
    modelService:
      enabled: true
      minAvailable: 1
  externalDatabase:
    enabled: true
    host: vela.postgres.database.azure.com
    port: 5432
    name: aodp
    existingSecret: vela-db-credentials
  externalMinio:
    # Azure Blob doesn't speak the S3 API natively - either front it with an
    # S3-compatible gateway, or run a small dedicated MinIO cluster (its own
    # nodes/disks, not this chart's in-cluster single-replica one) and point
    # here at that instead.
    enabled: true
    endpoint: vela-artifacts.example.blob.core.windows.net
    existingSecret: vela-s3-credentials
  healthChecks:
    backend:
      enabled: true
    modelService:
      enabled: true
  autoscaling:
    backend:
      enabled: true

# Create vela-db-credentials / vela-s3-credentials Secrets (see above)
# before installing, and an HPA (see above) after.
```

## Applying either example

```bash
helm install vela ./helm/vela -f production-values-eks.yaml \
  --set secrets.groqApiKey=gsk_... \
  --set secrets.githubToken=ghp_... \
  --set registry.ghcr.username=<github-username> \
  --set registry.ghcr.password=<ghcr-pat>
```

(`database.password`/`minio.rootPassword` are omitted - irrelevant once
`externalDatabase`/`externalMinio` are enabled, see above.)
