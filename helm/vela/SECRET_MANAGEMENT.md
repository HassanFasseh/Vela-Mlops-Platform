# Secret management

Vela's Helm chart supports three ways to get secrets (LLM API keys, the
database password, MinIO's root password, the GitHub token, the GHCR pull
token) into the cluster, selected by `secrets.backend` in `values.yaml`:

| `secrets.backend` | What happens | Requires |
|---|---|---|
| `kubernetes` (default) | Plain `Secret` objects rendered from `values.yaml` - current/existing behavior, no change | nothing extra |
| `vault` | backend-app's secrets are injected at pod startup by the **Vault Agent Injector** | Vault + the injector installed in-cluster |
| `external-secrets` | Every secret is synced from an external store by the **External Secrets Operator** (ESO) | ESO installed + a configured `(Cluster)SecretStore` |

Only one backend is active at a time. Switching `secrets.backend` alone
isn't enough for `vault`/`external-secrets` - each also has its own
`enabled: true` flag, a deliberate double-flag so a stray `--set
secrets.backend=vault` can't silently change how secrets are injected.

**Read this before picking `vault`:** it covers backend-app's own
application secrets only - see [Scope of the vault backend](#scope-of-the-vault-backend-what-it-does-not-cover)
below before relying on it for everything.

---

## Backend 1: Kubernetes Secrets (default)

No setup - this is what `helm install` does today. See the main
[README.md](README.md) for the install command and value reference.

---

## Backend 2: HashiCorp Vault

### 1. Install the Vault Agent Injector

If you don't already run Vault, the quickest path is the official Helm
chart, which installs both a Vault server (dev/single-node here - use HA
mode for production) and the injector:

```bash
helm repo add hashicorp https://helm.releases.hashicorp.com
helm repo update
helm install vault hashicorp/vault \
  --set "server.dev.enabled=true" \
  --set "injector.enabled=true"
```

If Vault already runs somewhere reachable from the cluster, install just
the injector:

```bash
helm install vault hashicorp/vault \
  --set "server.enabled=false" \
  --set "injector.enabled=true" \
  --set "injector.externalVaultAddr=https://vault.company.internal:8200"
```

Confirm the injector's mutating webhook is up:

```bash
kubectl get pods -l app.kubernetes.io/name=vault-agent-injector
```

### 2. Enable the Kubernetes auth method in Vault

```bash
vault auth enable kubernetes

vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc:443"
```

(Run this against Vault itself - e.g. `kubectl exec -it vault-0 -- vault ...`
if you installed it with the chart above.)

### 3. Store Vela's secrets in Vault

One KV v2 entry, one key per env var backend-app needs - this matches
`secrets.vault.path` (default `secret/vela`) and the generic
`{{- range $k, $v := .Data.data }}` template in
[`vault-annotations.tpl`](templates/vault-annotations.tpl), which exports
*whatever* keys exist at that path, so add/remove keys here freely:

```bash
vault kv put secret/vela \
  GROQ_API_KEY="gsk_..." \
  GEMINI_API_KEY="..." \
  DATABASE_URL="postgresql://vela:secure_password@postgres:5432/vela" \
  MINIO_ENDPOINT="minio:9000" \
  MINIO_ACCESS_KEY="minioadmin" \
  MINIO_SECRET_KEY="secure_password" \
  GITHUB_TOKEN="ghp_..." \
  GITHUB_REPO="HassanFasseh/vela"
```

### 4. Create a policy granting read access

```bash
vault policy write vela-backend - <<POLICY
path "secret/data/vela" {
  capabilities = ["read"]
}
POLICY
```

(KV v2 stores data under `secret/data/<path>`, not `secret/<path>` - the
policy path needs `data/` even though `secrets.vault.path` in `values.yaml`
and the `vault kv put`/`vault.hashicorp.com/agent-inject-secret-*` annotation
don't.)

### 5. Create the Kubernetes auth role

Binds a Kubernetes ServiceAccount + namespace to the policy above.
`vela-backend` here must match `secrets.vault.role`, and the service account
must match `rbac.serviceAccountName` (default: `default`) in the namespace
you're installing Vela into:

```bash
vault write auth/kubernetes/role/vela-backend \
  bound_service_account_names=default \
  bound_service_account_namespaces=default \
  policies=vela-backend \
  ttl=1h
```

### 6. Create the three secrets vault mode doesn't cover

Read [Scope of the vault backend](#scope-of-the-vault-backend-what-it-does-not-cover)
below for why - short version: `secrets.yaml`'s native Secrets only render
when `secrets.backend: kubernetes`, but Postgres/MinIO's own bootstrap
credentials and the GHCR pull secret can't come from Vault at all, so these
three need to exist before `helm install` in vault mode too:

```bash
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password=<ghcr-pat>

kubectl create secret generic postgres-secret \
  --from-literal=POSTGRES_DB=vela \
  --from-literal=POSTGRES_USER=vela \
  --from-literal=POSTGRES_PASSWORD=secure_password \
  --from-literal=DATABASE_URL='postgresql://vela:secure_password@postgres:5432/vela'

kubectl create secret generic minio-secret \
  --from-literal=MINIO_ENDPOINT=minio:9000 \
  --from-literal=MINIO_ROOT_USER=minioadmin \
  --from-literal=MINIO_ROOT_PASSWORD=secure_password
```

Use the same `secure_password` values here as in the `vault kv put` call in
step 3 - Vault gives backend-app its copy of `DATABASE_URL`/MinIO creds,
these plain Secrets give Postgres/MinIO themselves theirs, and the two need
to actually match.

### 7. Install Vela with the vault backend

```bash
helm install vela ./helm/vela \
  --set secrets.backend=vault \
  --set secrets.vault.enabled=true \
  --set secrets.vault.role=vela-backend \
  --set secrets.vault.path=secret/vela \
  --set database.password=secure_password \
  --set minio.rootPassword=secure_password \
  --set registry.ghcr.username=<github-username> \
  --set registry.ghcr.password=<ghcr-pat>
```

`database.password`/`minio.rootPassword`/`registry.ghcr.*` are harmless
placeholders in this command, not load-bearing - in vault mode `secrets.yaml`
doesn't render `postgres-secret`/`minio-secret`/`ghcr-secret` at all (see
below), so nothing actually reads these three values. Step 6's `kubectl
create secret` commands are what really sets Postgres/MinIO/the pull
secret's credentials; keep them consistent with each other rather than with
whatever you pass here.

Verify the sidecar actually injected and rendered the file:

```bash
kubectl get pod -l app=backend-app -o jsonpath='{.items[0].spec.containers[*].name}'
# expect: vault-agent backend-app

kubectl exec deploy/backend-app -c backend-app -- cat /vault/secrets/config
# expect: export GROQ_API_KEY="gsk_..." (etc.)
```

### Scope of the vault backend - what it does not cover

Vault Agent Injector adds an init container + sidecar to the **same pod**,
authenticated via that pod's own ServiceAccount. That model can't reach two
things Vela also needs, which is why step 6 above creates them by hand
instead:

- **The GHCR image pull secret.** Kubelet has to pull the pod's image
  *before* any container in the pod - including the Vault Agent init
  container - can run. A secret injected from inside the pod can't
  retroactively supply the credential kubelet needed to start the pod in
  the first place.
- **Postgres/MinIO's own bootstrap credentials.** Wiring Vault into those
  pods too is possible in principle (add the same annotations, override
  `command` to source the rendered file before exec'ing each image's real
  entrypoint - the trick used for backend-app in
  [`backend-deployment.yaml`](templates/backend-deployment.yaml)) but this
  chart doesn't do it, since it means depending on undocumented internals of
  the upstream `postgres`/`minio` images' entrypoint scripts rather than
  Vela's own, known `Dockerfile.backend` CMD.

So `secrets.backend: vault` only changes how **backend-app** consumes
`GROQ_API_KEY`/`GEMINI_API_KEY`/`DATABASE_URL`/the MinIO client
credentials/`GITHUB_TOKEN`/`GITHUB_REPO`. `secrets.yaml` gates its *entire*
contents (including `postgres-secret`/`minio-secret`/`ghcr-secret`) on
`secrets.backend == "kubernetes"`, so none of those three render in vault
mode - hence step 6's manual `kubectl create secret` calls, which need to
run once before `helm install`/`upgrade` and don't need to be repeated
afterwards (Helm doesn't touch Secrets it isn't managing).

If you want Postgres/MinIO/the pull secret *also* externally managed
instead of hand-created, use `external-secrets` - it has no such gap (see
below): ESO recreates all three under the same names Postgres/MinIO/kubelet
already expect.

### Rotating a secret (Vault backend)

```bash
vault kv put secret/vela GROQ_API_KEY="gsk_new..."
```

The sidecar re-renders `/vault/secrets/config` automatically (poll interval
governed by the injector's lease/TTL settings) - no `helm upgrade` needed.
Existing pods do **not** re-source the file into their already-running
process env on their own, though, since `export`-ing into a shell only
affects that shell and whatever it execs - restart the pods to pick up the
new value:

```bash
kubectl rollout restart deployment/backend-app
```

---

## Backend 3: External Secrets Operator (ESO)

Works with AWS Secrets Manager, Azure Key Vault, GCP Secret Manager, and
others - the `(Cluster)SecretStore` you point at decides which.

### 1. Install ESO

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm repo update
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace
```

Confirm the CRDs and controller are up:

```bash
kubectl get crd | grep external-secrets.io
kubectl get pods -n external-secrets
```

### 2. Create a ClusterSecretStore

One example per provider - pick the one matching where you actually store
secrets. Each needs its own cloud-side credential (an IAM role, a service
principal, a GCP service account key) with read access to the relevant
secrets; see ESO's own docs for the exact auth object shape per provider,
this is the minimum to get the store itself registered.

**AWS Secrets Manager:**

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: cluster-secret-store
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1
      auth:
        jwt:
          serviceAccountRef:
            name: eso-irsa
            namespace: external-secrets
```

**Azure Key Vault:**

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: cluster-secret-store
spec:
  provider:
    azurekv:
      vaultUrl: "https://your-vault.vault.azure.net"
      authType: WorkloadIdentity
      serviceAccountRef:
        name: eso-workload-identity
        namespace: external-secrets
```

**GCP Secret Manager:**

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: cluster-secret-store
spec:
  provider:
    gcpsm:
      projectID: your-gcp-project
      auth:
        workloadIdentity:
          clusterLocation: us-central1
          clusterName: your-gke-cluster
          serviceAccountRef:
            name: eso-workload-identity
            namespace: external-secrets
```

```bash
kubectl apply -f cluster-secret-store.yaml
kubectl get clustersecretstore cluster-secret-store
# STATUS should read "Valid" once ESO can reach the provider
```

If you'd rather scope credentials per-namespace instead of cluster-wide,
use `SecretStore` (namespaced) instead of `ClusterSecretStore` and set
`secrets.externalSecrets.secretStoreRef.kind: SecretStore`.

### 3. Map secret paths

Store each of the six secrets in your provider under whatever naming
convention you like, then point `secrets.externalSecrets.remoteRefs` at
them (defaults shown):

```yaml
secrets:
  externalSecrets:
    remoteRefs:
      groqApiKey: vela/groq-api-key
      geminiApiKey: vela/gemini-api-key
      githubToken: vela/github-token
      databasePassword: vela/database-password
      minioRootPassword: vela/minio-root-password
      ghcrToken: vela/ghcr-token
```

The value on the right is the *key/path in your provider*, not a
Kubernetes name - e.g. for AWS Secrets Manager that's the secret's name or
ARN (`vela/groq-api-key`), for Azure Key Vault a secret name, for GCP
Secret Manager a secret ID.

Non-secret fields (`database.name`/`database.user`, `minio.endpoint`/
`minio.rootUser`, `secrets.githubRepo`, `registry.ghcr.username`/
`registry.server`) stay in `values.yaml` as plain values - only the six
above are fetched at reconcile time. See
[`external-secrets.yaml`](templates/external-secrets.yaml) for exactly how
they're combined into each Secret's `target.template`.

### 4. Install Vela with the external-secrets backend

```bash
helm install vela ./helm/vela \
  --set secrets.backend=external-secrets \
  --set secrets.externalSecrets.enabled=true \
  --set database.password=unused-eso-will-overwrite-DATABASE_URL-and-POSTGRES_PASSWORD \
  --set minio.rootPassword=unused-eso-will-overwrite-MINIO_ROOT_PASSWORD
```

`database.password`/`minio.rootPassword` are still declared as "required"
by the chart's defaults (blank), but their *values* here don't matter in
external-secrets mode for `postgres-secret`/`minio-secret` themselves -
ESO's `target.template` overwrites `POSTGRES_PASSWORD`/`DATABASE_URL`/
`MINIO_ROOT_PASSWORD` with the fetched value once it reconciles (pass
anything non-empty to satisfy Helm's own templating; ESO wins the race).
`registry.ghcr.password` similarly doesn't need to be a real PAT in this
mode - the `ghcr-secret` ExternalSecret fetches the real one from
`remoteRefs.ghcrToken`.

Verify each ExternalSecret synced:

```bash
kubectl get externalsecret
# SYNCED should read True for all six

kubectl get secret groq-secret -o jsonpath='{.data.GROQ_API_KEY}' | base64 -d
```

### Rotating a secret (external-secrets backend)

Update the value in your provider (AWS/Azure/GCP console or CLI) - ESO
re-fetches on its own schedule (`secrets.externalSecrets.refreshInterval`,
default `1h`; lower it, e.g. `5m`, if you need faster propagation). No
`helm upgrade` needed. As with Vault, restart the consuming pods to pick up
the new value in their live process env:

```bash
kubectl rollout restart deployment/backend-app deployment/postgres deployment/minio
```

---

## Migrating from Kubernetes Secrets to Vault

Zero-downtime path - nothing gets deleted until the new backend is proven
working:

1. **Read out the current values.** Either from what you passed to
   `helm install`/`--set` originally, or from the live Secrets:
   ```bash
   kubectl get secret groq-secret -o jsonpath='{.data.GROQ_API_KEY}' | base64 -d
   kubectl get secret postgres-secret -o jsonpath='{.data.DATABASE_URL}' | base64 -d
   # ...repeat for gemini-secret, minio-secret, github-secret
   ```
2. **Install/point at Vault** and complete steps 1–5 under
   [Backend 2](#backend-2-hashicorp-vault) above, seeding
   `vault kv put secret/vela ...` with the values you just read out.
3. **Before upgrading, protect `ghcr-secret`/`postgres-secret`/
   `minio-secret` from deletion.** They already exist (Helm created them
   under the current `kubernetes` backend) - the moment `secrets.backend`
   stops being `kubernetes`, `secrets.yaml` stops rendering them, and a
   plain `helm upgrade` deletes anything it previously managed that drops
   out of the rendered manifest set. Postgres/MinIO's actual data password
   can't retroactively change, so losing that Secret is a real outage, not
   just a config gap. Mark them "keep" instead:
   ```bash
   kubectl annotate secret ghcr-secret postgres-secret minio-secret \
     helm.sh/resource-policy=keep
   ```
4. **Upgrade the release** with `secrets.backend=vault`:
   ```bash
   helm upgrade vela ./helm/vela \
     --set secrets.backend=vault \
     --set secrets.vault.enabled=true \
     --reuse-values
   ```
5. **Verify** the new pod actually has the Vault sidecar and the right
   values (`kubectl exec ... -- cat /vault/secrets/config`, and confirm
   backend-app is actually healthy - hit `/dashboard` or check
   `kubectl logs`) before moving on.
6. **Only after confirming**, stop maintaining the old values anywhere
   else you'd written them down (CI secrets, a password manager entry kept
   "just in case"). The live `groq-secret`/`gemini-secret`/`github-secret`
   Kubernetes Secret objects are gone the moment step 4's `helm upgrade`
   applies; `postgres-secret`/`minio-secret`/`ghcr-secret` are still there
   untouched, thanks to the `resource-policy: keep` annotation from step 3.

To roll back:

```bash
helm upgrade vela ./helm/vela \
  --set secrets.backend=kubernetes \
  --set secrets.groqApiKey=... \
  --set secrets.geminiApiKey=... \
  --set secrets.githubToken=... \
  --reuse-values
```

No need to touch `postgres-secret`/`minio-secret`/`ghcr-secret` first -
Helm still owns them (step 3 only told it not to *delete* them while they
were temporarily out of the rendered set, not that it stopped tracking
them), so this upgrade updates them in place like any other resource.
Afterwards, `kubectl annotate secret postgres-secret minio-secret
ghcr-secret helm.sh/resource-policy-` removes the now-unneeded `keep`
marker (the trailing `-` deletes the annotation). `groqApiKey`/
`geminiApiKey`/`githubToken` need re-supplying since they're not stored in
`values.yaml` in vault mode, only in Vault.

*(If you instead reach this rollback from a fresh `vault`-backend install
that used step 6's `kubectl create secret` - not this migration's `keep`
annotation - those three Secrets have no Helm ownership metadata at all,
and `helm upgrade` will refuse to adopt them: `kubectl delete secret
postgres-secret minio-secret ghcr-secret` first, then run the same
`helm upgrade` above with `database.password`/`minio.rootPassword`/
`registry.ghcr.*` also re-supplied so Helm has real values to recreate
them with.)*

Migrating to `external-secrets` follows the same shape: install ESO +
ClusterSecretStore, put the same six values into your external provider
under `secrets.externalSecrets.remoteRefs`' paths, then `helm upgrade
--set secrets.backend=external-secrets --set
secrets.externalSecrets.enabled=true --reuse-values`. This migration has no
equivalent to the vault caveat above - `postgres-secret`/`minio-secret`/
`ghcr-secret` are recreated by ESO with the same names Postgres/MinIO/kubelet
already expect, so there's nothing left behind to reconcile by hand.
