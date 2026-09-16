"""
Kubernetes operations for cloud-native custom model deployments.

One base image (ghcr.io/hassanfasseh/vela/custom-runner:base - see
custom-runner/base/) is shared by every custom deployment; what makes
each one different is mounted in at runtime instead of baked into a
per-deployment image build:

    predict.py     -> a ConfigMap, mounted as a single file (sub_path)
    model_files/   -> a PersistentVolumeClaim, populated by a one-shot
                       Job that mirrors it out of MinIO (the durable
                       copy - see /api/v1/upload-custom-model in main.py,
                       which writes there first)

Naming: the Deployment/Service both use the deployment's own `name`
(unprefixed - this is what /api/v1/predict already builds its target
URL from: http://{deployment.name}.default.svc.cluster.local). The
ConfigMap and Job are deterministic functions of that same name
(f"{name}-predict", f"{name}-download") and never stored separately.
The PVC's name IS stored (Deployment.pvc_name) - see the column's own
comment in db/models.py for why it, specifically, isn't just re-derived
the same way.

Orchestration note (see get_status() below): item 4 in the request this
shipped from describes "once the Job completes, kubectl apply a
Deployment + Service" as a discrete step. There's no long-running worker
in this backend to observe that transition, so instead of blocking the
upload request on it (bad: could be a multi-minute wait, HTTP timeouts,
etc.) get_status() creates the Deployment+Service itself, lazily, the
first time it's polled after the Job succeeds - safe to call on every
poll since both are idempotent (already-exists is treated as success,
not an error).
"""

import os
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.rest import ApiException

NAMESPACE = "default"
# :base is a floating tag - a pod already running it keeps whatever
# digest it pulled at creation, and (worse) a *new* deployment created
# after a rebuild could still resolve the same cached digest depending
# on kubelet/registry image caching, silently running stale code with no
# indication anything's wrong. build-base-runner.yml now also pushes a
# git-SHA-suffixed tag (custom-runner:base-<sha>) and patches this env
# var onto the backend Deployment after every successful build, so a new
# custom deployment always resolves to a concrete, unambiguous image -
# :base itself is kept only as a human-readable fallback for a backend
# pod that hasn't picked up that env var yet (a fresh install, say).
RUNTIME_IMAGE = os.environ.get("CUSTOM_RUNNER_IMAGE", "ghcr.io/hassanfasseh/vela/custom-runner:base")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio.default.svc.cluster.local:9000")


def _clients():
    config.load_incluster_config()
    return client.CoreV1Api(), client.AppsV1Api(), client.BatchV1Api()


def _labels(name: str) -> dict:
    return {"app": name, "managed-by": "platform", "model-type": "custom"}


# custom-runner:base exposes /metrics on the same port as /predict (see
# custom-runner/base/main.py) - these are the classic annotation-based
# scrape hints. Note: the Prometheus actually running in this cluster is
# kube-prometheus-stack (Prometheus Operator), which discovers targets
# via ServiceMonitor/PodMonitor CRDs, not these annotations, by default
# - see k8s/model-service-monitor.yaml for the one target that's
# currently wired up that way, and k8s/platform-runner-podmonitor.yaml
# for the PodMonitor that actually makes these pods (and model-runner's,
# same managed-by=platform label) scraped. Set regardless, since they're
# the right metadata either way and cost nothing.
_PROMETHEUS_ANNOTATIONS = {
    "prometheus.io/scrape": "true",
    "prometheus.io/path": "/metrics",
    "prometheus.io/port": "8000",
}


def _ignore_404(fn, *args, **kwargs):
    """Delete calls in cleanup should succeed even if the resource is
    already gone (partial previous cleanup, manual deletion, ...) -
    only a 404 is swallowed, anything else still raises."""
    try:
        fn(*args, **kwargs)
    except ApiException as e:
        if e.status != 404:
            raise


def configmap_name(name: str) -> str:
    return f"{name}-predict"


def job_name(name: str) -> str:
    return f"{name}-download"


def pvc_name_for(name: str) -> str:
    return f"{name}-model-files"


# ── Provisioning ────────────────────────────────────────────────────────────

def create_predict_configmap(name: str, predict_content: str) -> str:
    """Upsert (create, or replace if this deployment_name was used
    before) a ConfigMap holding predict.py's content under the key
    "predict.py" - mounted with sub_path so the pod sees exactly
    /app/predict.py, not a directory."""
    core_v1, _, _ = _clients()
    cm_name = configmap_name(name)
    cm = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=cm_name, labels=_labels(name)),
        data={"predict.py": predict_content},
    )
    try:
        core_v1.create_namespaced_config_map(NAMESPACE, cm)
    except ApiException as e:
        if e.status == 409:
            core_v1.replace_namespaced_config_map(cm_name, NAMESPACE, cm)
        else:
            raise
    return cm_name


def create_model_pvc(name: str, size_gb: int = 1) -> str:
    """Create the PVC model_files/ downloads into. Storage requests are
    immutable after creation, so a pre-existing PVC (same deployment_name
    re-uploaded) is left as-is rather than resized - only a fresh upload
    under a new deployment_name gets the requested size."""
    core_v1, _, _ = _clients()
    name_ = pvc_name_for(name)
    pvc = client.V1PersistentVolumeClaim(
        metadata=client.V1ObjectMeta(name=name_, labels=_labels(name)),
        spec=client.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            resources=client.V1ResourceRequirements(requests={"storage": f"{size_gb}Gi"}),
        ),
    )
    try:
        core_v1.create_namespaced_persistent_volume_claim(NAMESPACE, pvc)
    except ApiException as e:
        if e.status != 409:
            raise
    return name_


# Runs inside the download Job below via `python3 -c` - no shell, so no
# quoting to get wrong the way the old `mc alias set ... && mc mirror
# ...` one-liner did. MINIO_PATH is already bucket-prefixed (e.g.
# "models/workspace-1/custom/my-model/model_files" - see
# create_download_job) and split into bucket + prefix the same way `mc`
# addressing does.
_DOWNLOAD_SCRIPT = """
from minio import Minio
import os, pathlib

client = Minio(os.environ['MINIO_ENDPOINT'].replace('http://', ''),
               access_key=os.environ['MINIO_ACCESS_KEY'],
               secret_key=os.environ['MINIO_SECRET_KEY'],
               secure=False)

minio_path = os.environ['MINIO_PATH']
bucket = minio_path.split('/')[0]
prefix = '/'.join(minio_path.split('/')[1:])

pathlib.Path('/model_files').mkdir(exist_ok=True)
for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
    dest = '/model_files/' + obj.object_name.split('/')[-1]
    client.fget_object(bucket, obj.object_name, dest)
    print(f'Downloaded {obj.object_name} to {dest}')
"""


def create_download_job(name: str, minio_path: str, pvc: str) -> str:
    """(Re-)run the Job that copies {minio_path}/model_files/ (MinIO,
    already bucket-prefixed - see main.py's upload endpoint) into the
    PVC. Runs custom-runner:base itself (already pulled onto any node
    that's run a custom deployment, and ships the minio Python client -
    see custom-runner/base/Dockerfile) rather than minio/mc:latest,
    which was hitting Docker Hub's anonymous pull-rate limit in
    practice; GHCR doesn't have that problem, and reusing the one image
    every custom deployment already needs means one fewer image for the
    node to have to pull at all in the common case where it's cached.

    Jobs are run-once, not meant to be reused in place, so any previous
    run of this exact Job (an earlier upload/redeploy of the same
    deployment_name) is deleted first - Background propagation so this
    doesn't block waiting for the old Job's pod to finish terminating.
    """
    _, _, batch_v1 = _clients()
    jname = job_name(name)
    _ignore_404(batch_v1.delete_namespaced_job, jname, NAMESPACE, propagation_policy="Background")

    container = client.V1Container(
        name="download",
        image=RUNTIME_IMAGE,
        # IfNotPresent, not Always (unlike create_runtime_deployment) -
        # this image rarely changes between runs of this Job, and
        # preferring whatever's already cached on the node is the whole
        # point of reusing it here over a separate always-pulled image.
        image_pull_policy="IfNotPresent",
        command=["python3", "-c", _DOWNLOAD_SCRIPT],
        env=[
            client.V1EnvVar(name="MINIO_ENDPOINT", value=MINIO_ENDPOINT),
            client.V1EnvVar(name="MINIO_PATH", value=f"{minio_path}/model_files"),
            client.V1EnvVar(
                name="MINIO_ACCESS_KEY",
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(name="minio-secret", key="MINIO_ROOT_USER")
                ),
            ),
            client.V1EnvVar(
                name="MINIO_SECRET_KEY",
                value_from=client.V1EnvVarSource(
                    secret_key_ref=client.V1SecretKeySelector(name="minio-secret", key="MINIO_ROOT_PASSWORD")
                ),
            ),
        ],
        volume_mounts=[client.V1VolumeMount(name="model-files", mount_path="/model_files")],
    )
    pod_spec = client.V1PodSpec(
        # custom-runner:base lives on GHCR, unlike the Docker Hub public
        # minio/mc image it replaces - needs the same pull secret the
        # runtime Deployment uses.
        image_pull_secrets=[client.V1LocalObjectReference(name="ghcr-secret")],
        containers=[container],
        restart_policy="Never",
        volumes=[
            client.V1Volume(
                name="model-files",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name=pvc),
            )
        ],
    )
    job = client.V1Job(
        metadata=client.V1ObjectMeta(name=jname, labels=_labels(name)),
        spec=client.V1JobSpec(
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=_labels(name)), spec=pod_spec
            ),
            backoff_limit=2,
            ttl_seconds_after_finished=3600,
        ),
    )
    batch_v1.create_namespaced_job(NAMESPACE, job)
    return jname


def create_runtime_deployment(name: str, cm_name: str, pvc: str, input_type: str, input_schema: str):
    """Deployment + Service running custom-runner:base with this
    deployment's predict.py/model_files mounted in. Idempotent - a
    pre-existing Deployment/Service (redeploy, or a re-poll after the
    first one already created them) is replaced/left alone rather than
    erroring."""
    core_v1, apps_v1, _ = _clients()

    env = [client.V1EnvVar(name="INPUT_TYPE", value=input_type or "text")]
    if input_schema:
        env.append(client.V1EnvVar(name="INPUT_SCHEMA", value=input_schema))

    container = client.V1Container(
        name="custom-runner",
        image=RUNTIME_IMAGE,
        image_pull_policy="Always",
        ports=[client.V1ContainerPort(name="http", container_port=8000)],
        env=env,
        volume_mounts=[
            client.V1VolumeMount(name="predict-script", mount_path="/app/predict.py", sub_path="predict.py"),
            client.V1VolumeMount(name="model-files", mount_path="/app/model_files"),
        ],
        resources=client.V1ResourceRequirements(
            requests={"memory": "512Mi", "cpu": "80m"},
            limits={"memory": "2Gi", "cpu": "500m"},
        ),
    )
    pod_spec = client.V1PodSpec(
        image_pull_secrets=[client.V1LocalObjectReference(name="ghcr-secret")],
        containers=[container],
        volumes=[
            client.V1Volume(
                name="predict-script",
                config_map=client.V1ConfigMapVolumeSource(name=cm_name, items=[
                    client.V1KeyToPath(key="predict.py", path="predict.py")
                ]),
            ),
            client.V1Volume(
                name="model-files",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(claim_name=pvc),
            ),
        ],
    )
    deployment = client.V1Deployment(
        metadata=client.V1ObjectMeta(name=name, labels=_labels(name)),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": name}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=_labels(name), annotations=_PROMETHEUS_ANNOTATIONS),
                spec=pod_spec,
            ),
        ),
    )
    try:
        apps_v1.create_namespaced_deployment(NAMESPACE, deployment)
    except ApiException as e:
        if e.status == 409:
            apps_v1.replace_namespaced_deployment(name, NAMESPACE, deployment)
        else:
            raise

    service = client.V1Service(
        metadata=client.V1ObjectMeta(name=name, labels=_labels(name)),
        spec=client.V1ServiceSpec(
            type="ClusterIP",
            selector={"app": name},
            ports=[client.V1ServicePort(name="http", port=80, target_port=8000)],
        ),
    )
    try:
        core_v1.create_namespaced_service(NAMESPACE, service)
    except ApiException as e:
        if e.status != 409:
            raise


def create_image_deployment(name: str, image: str, input_type: str, input_schema: str, local: bool = False):
    """Deployment + Service for the "Docker image" custom-deploy path -
    an admin-supplied, already-built image, as opposed to
    create_runtime_deployment's mount-at-runtime flow (predict.py/
    model_files onto custom-runner:base). No ConfigMap/PVC: the image is
    trusted to already contain everything it needs, and is expected to
    implement the same contract every other runner in this platform does
    (GET /health, POST /predict, GET /metrics, all on :8000).

    The readinessProbe against GET /health is what actually enforces that
    contract - Kubernetes won't report the pod Ready (and so
    get_image_status won't report "running") until the admin's image
    answers it correctly, so there's no separate smoke-test step to write
    here the way the file-build pipeline needs one.

    local=True is for the "upload a local Docker image" path (see
    backend.app.services.containerd_import): the image already sits in
    the node's containerd image store, imported straight off the admin's
    tar with no registry involved at all, so pulling would just fail (or
    worse, silently resolve some unrelated same-named image from a real
    registry) - imagePullPolicy: Never tells kubelet to use exactly the
    local one, and ghcr-secret is irrelevant to a pull that never happens.

    Idempotent, same replace-on-409 pattern as create_runtime_deployment -
    redeploying under the same name (e.g. a new image tag) replaces the
    Deployment in place."""
    core_v1, apps_v1, _ = _clients()

    env = [client.V1EnvVar(name="INPUT_TYPE", value=input_type or "text")]
    if input_schema:
        env.append(client.V1EnvVar(name="INPUT_SCHEMA", value=input_schema))

    container = client.V1Container(
        name="custom-runner",
        image=image,
        image_pull_policy="Never" if local else "Always",
        ports=[client.V1ContainerPort(name="http", container_port=8000)],
        env=env,
        readiness_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/health", port=8000),
            initial_delay_seconds=5,
            period_seconds=5,
            failure_threshold=6,
        ),
        resources=client.V1ResourceRequirements(
            requests={"memory": "512Mi", "cpu": "80m"},
            limits={"memory": "2Gi", "cpu": "500m"},
        ),
    )
    pod_spec = client.V1PodSpec(
        # Present unconditionally for a registry-pulled image - harmless
        # for a public/Docker-Hub image (kubelet still falls back to an
        # anonymous pull), and is what makes a private image on this same
        # GHCR account work with no extra per-deployment credential UI.
        # Omitted for a local image: there's no pull to attach it to.
        image_pull_secrets=None if local else [client.V1LocalObjectReference(name="ghcr-secret")],
        containers=[container],
    )
    deployment = client.V1Deployment(
        metadata=client.V1ObjectMeta(name=name, labels=_labels(name)),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": name}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=_labels(name), annotations=_PROMETHEUS_ANNOTATIONS),
                spec=pod_spec,
            ),
        ),
    )
    try:
        apps_v1.create_namespaced_deployment(NAMESPACE, deployment)
    except ApiException as e:
        if e.status == 409:
            apps_v1.replace_namespaced_deployment(name, NAMESPACE, deployment)
        else:
            raise

    service = client.V1Service(
        metadata=client.V1ObjectMeta(name=name, labels=_labels(name)),
        spec=client.V1ServiceSpec(
            type="ClusterIP",
            selector={"app": name},
            ports=[client.V1ServicePort(name="http", port=80, target_port=8000)],
        ),
    )
    try:
        core_v1.create_namespaced_service(NAMESPACE, service)
    except ApiException as e:
        if e.status != 409:
            raise


def restart_deployment(name: str):
    """Rolling restart, the same way `kubectl rollout restart` does it -
    bump an annotation nobody reads except this, which changes the pod
    template and so triggers a new ReplicaSet. Used by the redeploy
    endpoint after the download Job refreshes the PVC, so the running
    pod actually picks up new model_files/ (predict.py via the
    ConfigMap mount updates on its own after a short kubelet propagation
    delay, but the already-running Python process never re-imports it
    without a restart either way)."""
    _, apps_v1, _ = _clients()
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()
                    }
                }
            }
        }
    }
    apps_v1.patch_namespaced_deployment(name, NAMESPACE, patch)


# ── Status ───────────────────────────────────────────────────────────────

def get_status(name: str, cm_name: str, pvc: str, input_type: str, input_schema: str) -> dict:
    """Polled by GET /api/v1/custom-model-status/{id}. Returns
    {"phase": ...} where phase is one of:
      downloading   Job running - model_files/ still copying from MinIO
      failed        Job failed
      provisioning  Job succeeded, Deployment created but not Ready yet
                     (also the phase returned right after creating it,
                     this call)
      running       Deployment has as many ready replicas as desired
    """
    _, apps_v1, batch_v1 = _clients()

    try:
        job = batch_v1.read_namespaced_job_status(job_name(name), NAMESPACE)
        job_failed = bool(job.status.failed)
        job_succeeded = bool(job.status.succeeded)
    except ApiException as e:
        if e.status == 404:
            # Genuinely never ran (shouldn't happen in the normal
            # upload flow) vs. already cleaned up post-TTL - either way,
            # nothing to report as failed, just not done yet.
            job_failed, job_succeeded = False, False
        else:
            raise

    if job_failed:
        return {"phase": "failed", "detail": "Model file download job failed"}
    if not job_succeeded:
        return {"phase": "downloading"}

    try:
        apps_v1.read_namespaced_deployment(name, NAMESPACE)
    except ApiException as e:
        if e.status == 404:
            create_runtime_deployment(name, cm_name, pvc, input_type, input_schema)
            return {"phase": "provisioning"}
        raise

    dep_status = apps_v1.read_namespaced_deployment_status(name, NAMESPACE)
    ready = dep_status.status.ready_replicas or 0
    desired = dep_status.spec.replicas or 1
    if ready >= desired:
        return {"phase": "running"}
    return {"phase": "provisioning"}


def get_image_status(name: str) -> dict:
    """Polled by GET /api/v1/custom-model-status/{id} for the "Docker
    image" path (Deployment.source == "image"). Unlike get_status()
    above there's no Job/ConfigMap/PVC to progress through first - the
    Deployment+Service are created synchronously by
    /api/v1/deploy-custom-image - so this only ever has to answer "is
    the pod ready yet, and if not, is it stuck." ready_replicas >=
    desired is trustworthy evidence the /predict contract is actually
    being served (not just that some process is running) because it's
    gated on create_image_deployment's readinessProbe.

    While not yet ready, checks for the two most common stuck states
    (bad image reference, or an image that crashes on startup) so the
    caller isn't left reporting "provisioning" forever with no clue why."""
    core_v1, apps_v1, _ = _clients()
    try:
        dep_status = apps_v1.read_namespaced_deployment_status(name, NAMESPACE)
    except ApiException as e:
        if e.status == 404:
            return {"phase": "failed", "detail": "Deployment not found - it may have failed to create."}
        raise

    ready = dep_status.status.ready_replicas or 0
    desired = dep_status.spec.replicas or 1
    if ready >= desired:
        return {"phase": "running"}

    pods = core_v1.list_namespaced_pod(NAMESPACE, label_selector=f"app={name}")
    for pod in pods.items:
        for cs in (pod.status.container_statuses or []):
            waiting = cs.state.waiting
            if waiting and waiting.reason in ("ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff"):
                return {"phase": "failed", "detail": f"{waiting.reason}: {waiting.message or 'container is not starting'}"}
    return {"phase": "provisioning"}


# ── Cleanup ──────────────────────────────────────────────────────────────

def delete_all(name: str, pvc: str = None):
    """Best-effort teardown of everything a custom deployment created -
    called when its Deployment DB row is deleted. Order doesn't matter
    for correctness (nothing here has an ownerReference chain forcing
    it), but Job before PVC avoids a brief window where a Job could
    still be trying to write to a PVC that's mid-deletion."""
    core_v1, apps_v1, batch_v1 = _clients()
    _ignore_404(apps_v1.delete_namespaced_deployment, name, NAMESPACE)
    _ignore_404(core_v1.delete_namespaced_service, name, NAMESPACE)
    _ignore_404(batch_v1.delete_namespaced_job, job_name(name), NAMESPACE, propagation_policy="Background")
    _ignore_404(core_v1.delete_namespaced_config_map, configmap_name(name), NAMESPACE)
    if pvc:
        _ignore_404(core_v1.delete_namespaced_persistent_volume_claim, pvc, NAMESPACE)


def delete_deployment_and_service(name: str):
    """Teardown for a HuggingFace deployment (model-deploy.yml's inline
    manifest: just a Deployment + Service, no ConfigMap/PVC/Job - using
    delete_all() here would be harmless (it's all _ignore_404'd) but
    misleading about what these deployments actually have."""
    core_v1, apps_v1, _ = _clients()
    _ignore_404(apps_v1.delete_namespaced_deployment, name, NAMESPACE)
    _ignore_404(core_v1.delete_namespaced_service, name, NAMESPACE)
