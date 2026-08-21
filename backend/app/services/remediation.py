import os
import requests
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://monitoring-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090")

def get_current_drift_score() -> float:
    try:
        r = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": "drift_score"}, timeout=5)
        result = r.json()["data"]["result"]
        if result:
            return float(result[0]["value"][1])
        return 0.0
    except Exception:
        return 0.0

def fire_github_issue(deployment_name: str, drift_score: float, target: str) -> dict:
    repo = target or GITHUB_REPO
    if not repo or not GITHUB_TOKEN:
        return {"status": "error", "response": "GitHub credentials not configured"}
    url = f"https://api.github.com/repos/{repo}/issues"
    body = f"""## Drift Alert — {deployment_name}

**Drift score:** {drift_score:.3f}
**Triggered at:** {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}

### What happened
The model `{deployment_name}` has exceeded its configured drift threshold. The input data distribution has shifted significantly from the reference window.

### Recommended actions
- [ ] Review recent prediction inputs for distribution shift
- [ ] Check if upstream data pipeline changed
- [ ] Consider retraining on recent data
- [ ] Review model card for known limitations

*This issue was automatically created by the AI-Operated Model Deployment Platform.*
"""
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
        json={"title": f"[Drift Alert] {deployment_name} drift score: {drift_score:.3f}", "body": body, "labels": ["drift-alert", "ml-ops"]},
        timeout=10
    )
    return {"status": "success" if resp.status_code == 201 else "error", "response": resp.text[:200]}

def fire_webhook(deployment_name: str, drift_score: float, target: str) -> dict:
    if not target:
        return {"status": "error", "response": "No webhook URL configured"}
    payload = {
        "event": "drift_threshold_exceeded",
        "deployment": deployment_name,
        "drift_score": drift_score,
        "timestamp": datetime.utcnow().isoformat(),
        "message": f"Model {deployment_name} drift score {drift_score:.3f} exceeded threshold"
    }
    try:
        resp = requests.post(target, json=payload, timeout=10)
        return {"status": "success" if resp.status_code < 400 else "error", "response": resp.text[:200]}
    except Exception as e:
        return {"status": "error", "response": str(e)}

def fire_retrain(deployment_name: str, drift_score: float, target: str) -> dict:
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return {"status": "error", "response": "GitHub credentials not configured"}
    workflow = target or "retrain.yml"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow}/dispatches"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
        json={"ref": "main", "inputs": {"deployment_name": deployment_name, "drift_score": str(drift_score)}},
        timeout=10
    )
    return {"status": "success" if resp.status_code == 204 else "error", "response": resp.text[:200]}

def check_and_fire(db: Session):
    from backend.app.db.models import RemediationConfig, RemediationLog, Deployment
    drift_score = get_current_drift_score()
    if drift_score == 0.0:
        return

    configs = db.query(RemediationConfig).filter(RemediationConfig.is_active == True).all()
    for config in configs:
        if drift_score < config.drift_threshold:
            continue
        # Cooldown: don't fire more than once per hour
        if config.last_triggered_at and datetime.utcnow() - config.last_triggered_at < timedelta(hours=1):
            continue

        deployment = db.query(Deployment).filter(Deployment.id == config.deployment_id).first()
        deployment_name = deployment.name if deployment else f"deployment-{config.deployment_id}"

        if config.action_type == "github_issue":
            result = fire_github_issue(deployment_name, drift_score, config.target)
        elif config.action_type == "webhook":
            result = fire_webhook(deployment_name, drift_score, config.target)
        elif config.action_type == "retrain":
            result = fire_retrain(deployment_name, drift_score, config.target)
        else:
            result = {"status": "error", "response": f"Unknown action type: {config.action_type}"}

        # Log the result
        log = RemediationLog(
            config_id=config.id,
            deployment_id=config.deployment_id,
            drift_score=drift_score,
            action_type=config.action_type,
            target=config.target,
            status=result["status"],
            response=result["response"]
        )
        db.add(log)
        config.last_triggered_at = datetime.utcnow()
        db.commit()
        print(f"[remediation] fired {config.action_type} for {deployment_name} (drift={drift_score:.3f}): {result['status']}", flush=True)
