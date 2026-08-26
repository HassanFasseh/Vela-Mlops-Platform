# Vela on GitLab CI

GitLab CI equivalents of the GitHub Actions workflows in
`.github/workflows/`. Same build/deploy behavior, packaged as GitLab CI/CD
so the project can run on either platform (or migrate).

| File | Equivalent to | Trigger |
|---|---|---|
| `deploy-backend.yml` | `.github/workflows/deploy-backend.yml` | push to `main` touching `backend/**` or `Dockerfile.backend`; also runnable manually |
| `deploy-model.yml` | `.github/workflows/model-deploy.yml` | manual only, with `model_name` / `task_type` / `deployment_name` variables |
| `build-base-runner.yml` | `.github/workflows/build-base-runner.yml` | manual only |
| `.gitlab-ci.yml` | - | master file that `include`s the three above |

None of these touch `model-service`'s own GitHub workflow (`deploy.yml`) -
only the three named in the request were ported.

## Getting GitLab to actually run this pipeline

`.gitlab-ci.yml` normally has to live at the repo root; this one is under
`gitlab-ci/` instead so it doesn't collide with (or get confused for) a
root pipeline file. Point GitLab at it one of two ways:

- **Project setting (no file move needed):** Settings → CI/CD → General
  pipelines → "CI/CD configuration file" → set it to
  `gitlab-ci/.gitlab-ci.yml`.
- **Or** copy/symlink `gitlab-ci/.gitlab-ci.yml` to `.gitlab-ci.yml` at the
  repo root. The `include: local:` paths inside it are already
  repo-root-relative (`gitlab-ci/deploy-backend.yml` etc.), so this works
  unchanged either way.

## Runner requirements

The build jobs need a runner that can run **privileged** Docker-in-Docker
(for `docker buildx` + QEMU cross-arch emulation) - GitLab.com's shared
Linux runners support this out of the box. A self-managed runner needs
`privileged = true` set on its `[runners.docker]` config.

## Setting up CI/CD variables

Settings → CI/CD → Variables. Recommended: mark secrets **Masked** and, for
anything with cluster/registry write access, **Protected** (limits them to
protected branches/tags - protect `main` if it isn't already).

### Registry - pick one

**Option A: GitHub Container Registry (GHCR)** - matches the current setup
described in the root `CLAUDE.md`:

| Variable | Value |
|---|---|
| `GHCR_USER` | Your GitHub username (e.g. `HassanFasseh`) |
| `GHCR_TOKEN` | A GitHub PAT with `write:packages` (and `read:packages`) scope - same PAT `CLAUDE.md` documents for recreating `ghcr-secret` by hand. It expires (~90 days); update this variable and re-run the pipeline when it does. |

Leave `GHCR_NAMESPACE` at its default (`hassanfasseh/vela`) or override it
via `--set`/a variable if you fork the image namespace elsewhere.

**Option B: GitLab Container Registry** - if `GHCR_TOKEN` is unset, every
job here falls back to it automatically. `CI_REGISTRY`,
`CI_REGISTRY_IMAGE`, `CI_REGISTRY_USER`, and `CI_REGISTRY_PASSWORD` are
**predefined by GitLab** for any project with the Container Registry
enabled - you don't set these yourself. Images end up at
`$CI_REGISTRY_IMAGE` (i.e. `registry.gitlab.com/<group>/<project>`)
instead of under `ghcr.io/hassanfasseh/vela`.

Nothing else changes: `deploy-backend`/`deploy-model` skip the
`ghcr-secret` step entirely in this mode (see the note on image pull
secrets below).

### Kubernetes cluster access

Two ways to give the pipeline a working `kubectl`, checked in this order:

**Option A - `KUBE_CONFIG` (simplest):** base64-encode a kubeconfig that
already points at your cluster and has permissions to `set image` /
`rollout status` on `backend-app`, `model-service`, and to `apply` model
Deployments/Services:

```bash
kubectl config view --minify --flatten -o yaml | base64 -w0
```

Set the result as a **File**-type or plain variable named `KUBE_CONFIG`
(mark it Masked + Protected). The pipeline decodes it straight into
`~/.kube/config`.

**Option B - OCI CLI (matches the GitHub Actions version exactly):** if
`KUBE_CONFIG` is unset, the pipeline derives a kubeconfig for an OKE
cluster the same way the GitHub Actions workflows do - via
`oci ce cluster create-kubeconfig`. Requires:

| Variable | Value |
|---|---|
| `OCI_USER_OCID` | OCI user OCID |
| `OCI_FINGERPRINT` | API key fingerprint |
| `OCI_TENANCY_OCID` | Tenancy OCID |
| `OCI_REGION` | e.g. `af-casablanca-1` |
| `OCI_PRIVATE_KEY` | The API signing key's PEM content (paste the whole `-----BEGIN...-----END-----` block as a **File**-type variable, or a plain multi-line variable) |
| `CLUSTER_OCID` | The OKE cluster's OCID |

If neither `KUBE_CONFIG` nor `CLUSTER_OCID` is set, the deploy jobs fail
fast with a clear error instead of hanging.

### Namespace

`K8S_NAMESPACE` defaults to `default` in each file - override it (as a
variable, or by editing the file) if Vela runs in a different namespace.

## Running the manual pipelines

`deploy-model.yml` and `build-base-runner.yml` never run automatically.
To run them:

1. CI/CD → Pipelines → **Run pipeline**.
2. For `deploy-model`, fill in the `model_name`, `task_type` (dropdown),
   and `deployment_name` variables shown on that page - GitLab's
   `variables.<name>.options`/`description` keys populate that form, the
   closest equivalent to GitHub's `workflow_dispatch` `type: choice`
   inputs.
3. Click **Run pipeline**, then hit the manual ▶ Play button on the
   `build-model-runner` job (and `deploy-model` after it finishes).

This differs from GitHub Actions in one way worth knowing: GitHub's
`workflow_dispatch` inputs are collected in the same dialog that starts the
run. GitLab's equivalent is the "Run pipeline" variables form - functionally
the same, but the manual jobs still show a separate Play button per job
rather than running as one atomic dispatched job.

## Differences from the GitHub Actions version

- **Registry is configurable, not hardcoded to GHCR.** Every job checks
  `GHCR_TOKEN` first and falls back to the GitLab Container Registry using
  GitLab's built-in `CI_REGISTRY_*` variables. The GitHub workflows only
  ever targeted `ghcr.io/hassanfasseh/vela`.
- **`ghcr-secret` is only (re)created when pushing to GHCR.** In GitLab
  Container Registry mode there's no separate long-lived pull-secret step
  - Kubernetes still needs an `imagePullSecret` to pull from
  `registry.gitlab.com`, but this chart doesn't manage one for that case;
  create it yourself (`kubectl create secret docker-registry ... --docker-server=registry.gitlab.com ...`, likely from a GitLab [deploy token](https://docs.gitlab.com/ee/user/project/deploy_tokens/) rather than a personal token) if you go that route.
- **Multi-arch builds run in `docker:24-dind`** instead of
  `docker/setup-buildx-action` + `docker/build-push-action`. Functionally
  equivalent - a `docker-container` buildx builder plus QEMU emulation via
  `tonistiigi/binfmt` - but self-hosted rather than a GitHub Action.
  `build-base-runner.yml` still only builds `linux/arm64`, matching the
  comment in the original workflow (OKE on Oracle Always Free is
  arm64-only).
- **Kubeconfig acquisition supports two paths**, `KUBE_CONFIG` or the OCI
  CLI flow; GitHub Actions only had the OCI CLI flow (`azure/setup-kubectl`
  + `oci ce cluster create-kubeconfig`). `KUBE_CONFIG` is the simpler
  option if you don't want to grant CI a full OCI API key.
- **`deploy-model`'s `task_type` choice** is expressed with GitLab's
  `variables.task_type.options` (Run-pipeline-page dropdown) rather than a
  `workflow_dispatch` `type: choice` input - see "Running the manual
  pipelines" above.
- **Shared setup lives in hidden jobs** (`.docker_build_template`,
  `.kubeconfig_template`, `.ghcr_pull_secret_template`), defined once in
  `deploy-backend.yml` and reused via `extends:`/`!reference` from the
  other two files - GitLab merges all `include`d files into one
  configuration before running, so this works across files without a
  separate "common.yml".
- **No workflow-level `permissions:` block** - GitLab jobs get an
  ephemeral `CI_JOB_TOKEN` scoped to the project automatically; there's no
  equivalent to GitHub's per-workflow `contents`/`packages` permission
  grants to configure.

## Files

- `deploy-backend.yml` - build stage builds+pushes `backend-app`, deploy
  stage `kubectl set image` + `kubectl rollout status`.
- `deploy-model.yml` - manual; builds `model-runner:<deployment_name>` with
  `MODEL_NAME`/`TASK_TYPE` build args, applies a Deployment+Service, waits
  for rollout, then runs the same throwaway `curl` health-check pod the
  GitHub Actions version does.
- `build-base-runner.yml` - manual; builds and pushes
  `custom-runner:base` from `custom-runner/base/` for `linux/arm64` only.
- `.gitlab-ci.yml` - includes the three files above into one pipeline.
