"""Syncs Deployment.status in the DB from live Kubernetes state.

/deploy-model (and /api/v1/upload-model, /api/v1/upload-custom-model)
create a Deployment row with status="pending"/"uploaded" and nothing
else ever flips it once the pod actually starts — GET
/teams/{id}/permissions (services/teams.py), and every other place that
reads Deployment.status straight from the DB rather than querying k8s
itself, would show that stale status forever for a model that's
actually running fine. sync_deployment_statuses() is run periodically
(see main.py's deployment_status_sync_loop, every 60s) to fix that up,
the same way GET /deployments already derives live status for its own
response — this just writes that derived status back to the DB instead
of only returning it.
"""
from sqlalchemy.orm import Session
from backend.app.db.models import Deployment


def sync_deployment_statuses(db: Session) -> int:
    """Updates every active Deployment row's status from the matching k8s
    Deployment's ready/desired replica counts. Returns how many rows
    actually changed (0 outside a real cluster, e.g. local dev/tests —
    load_incluster_config() fails there and this becomes a no-op rather
    than an error the caller has to handle).

    A Deployment row with no matching k8s Deployment yet (still building
    via GitHub Actions, or a custom model that hasn't finished uploading)
    is left untouched — there's nothing live to sync from yet, which
    isn't evidence the current status is wrong."""
    try:
        from kubernetes import client as k8s_client, config as k8s_config
        k8s_config.load_incluster_config()
    except Exception:
        return 0

    try:
        apps_v1 = k8s_client.AppsV1Api()
        k8s_deployments = apps_v1.list_namespaced_deployment(
            namespace="default", label_selector="managed-by=platform"
        )
    except Exception:
        return 0

    live_status_by_name = {}
    for d in k8s_deployments.items:
        ready = d.status.ready_replicas or 0
        desired = d.spec.replicas or 1
        live_status_by_name[d.metadata.name] = "running" if ready == desired else "starting"

    changed = 0
    for dep in db.query(Deployment).filter(Deployment.is_active == True).all():
        live_status = live_status_by_name.get(dep.name)
        if live_status and dep.status != live_status:
            dep.status = live_status
            changed += 1
    if changed:
        db.commit()
    return changed
