"""
Kubernetes operations for cloud-native custom model deployments.

One base image (ghcr.io/hassanfasseh/vela/custom-runner:base — see
custom-runner/base/) is shared by every custom deployment; what makes
each one different is mounted in at runtime instead of baked into a
per-deployment image build:

    predict.py     -> a ConfigMap, mounted as a single file (sub_path)
    model_files/   -> a PersistentVolumeClaim, populated by a one-shot
                       Job that mirrors it out of MinIO (the durable
                       copy — see /api/v1/upload-custom-model in main.py,
                       which writes there first)

Naming: the Deployment/Service both use the deployment's own `name`
(unprefixed — this is what /api/v1/predict already builds its target
URL from: http://{deployment.name}.default.svc.cluster.local). The
ConfigMap and Job are deterministic functions of that same name
(f"{name}-predict", f"{name}-download") and never stored separately.
The PVC's name IS stored (Deployment.pvc_name) — see the column's own
comment in db/models.py for why it, specifically, isn't just re-derived
the same way.

Orchestration note (see get_status() below): item 4 in the request this
shipped from describes "once the Job completes, kubectl apply a
Deployment + Service" as a discrete step. There's no long-running worker
in this backend to observe that transition, so instead of blocking the
upload request on it (bad: could be a multi-minute wait, HTTP timeouts,
etc.) get_status() creates the Deployment+Service itself, lazily, the
first time it's polled after the Job succeeds — safe to call on every
poll since both are idempotent (already-exists is treated as success,
not an error).
"""

import os
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.rest import ApiException

NAMESPACE = "default"
RUNTIME_IMAGE = "ghcr.io/hassanfasseh/vela/custom-runner:base"
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio.default.svc.cluster.local:9000")


def _clients():
    config.load_incluster_config()
    return client.CoreV1Api(), client.AppsV1Api(), client.BatchV1Api()


def _labels(name: str) -> dict:
    return {"app": name, "managed-by": "platform", "model-type": "custom"}


def _ignore_404(fn, *args, **kwargs):
    """Delete calls in cleanup should succeed even if the resource is
    already gone (partial previous cleanup, manual deletion, ...) —
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
    "predict.py" — mounted with sub_path so the pod sees exactly
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
    re-uploaded) is left as-is rather than resized — only a fresh upload
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


def create_download_job(name: str, minio_path: str, pvc: str) -> str:
    """(Re-)run the Job that mirrors {minio_path}/model_files/ (MinIO,
    already bucket-prefixed — see main.py's upload endpoint) into the
    PVC. Jobs are run-once, not meant to be reused in place, so any
    previous run of this exact Job (an earlier upload/redeploy of the
    same deployment_name) is deleted first — Background propagation so
    this doesn't block waiting for the old Job's pod to finish
    terminating."""
    _, _, batch_v1 = _clients()
    jname = job_name(name)
    _ignore_404(batch_v1.delete_namespaced_job, jname, NAMESPACE, propagation_policy="Background")

    container = client.V1Container(
        name="download",
        image="minio/mc:latest",
        command=["/bin/sh", "-c"],
        args=[
            f'mc alias set src http://{MINIO_ENDPOINT} "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" && '
            f'mc mirror --overwrite "src/{minio_path}/model_files/" /data/'
        ],
        env=[
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
        volume_mounts=[client.V1VolumeMount(name="model-files", mount_path="/data")],
    )
    pod_spec = client.V1PodSpec(
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
    deployment's predict.py/model_files mounted in. Idempotent — a
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
                metadata=client.V1ObjectMeta(labels=_labels(name)), spec=pod_spec
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
    """Rolling restart, the same way `kubectl rollout restart` does it —
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
      downloading   Job running — model_files/ still copying from MinIO
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
            # upload flow) vs. already cleaned up post-TTL — either way,
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


# ── Cleanup ──────────────────────────────────────────────────────────────

def delete_all(name: str, pvc: str = None):
    """Best-effort teardown of everything a custom deployment created —
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
