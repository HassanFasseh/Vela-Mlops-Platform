#!/usr/bin/env python3
"""
Seeds a LOCAL scratch SQLite database with realistic demo content: deployed
models with varied names/tasks/statuses, deployment history, remediation
configs + drift-trigger history, and tickets - so the admin screens
(Overview, Model Registry, the Monitoring/Drift model picker, Remediation,
Tickets) render with real content while the design-system migration is in
progress.

SAFETY: refuses to run unless DATABASE_URL is explicitly set, and refuses
to run against anything literally named app.db - the committed database is
never touched by this script.

IDEMPOTENT: re-running skips anything that already exists (matched by
name/title), so it's safe to run more than once - it only ever adds what's
missing.

IMPORTANT LIMITATION: the Monitoring/Drift pages' live numbers - per-model
health-check status, latency, req/min, drift score/charts, replica counts -
come from a real Prometheus + running Kubernetes pods (see
backend/app/services/timeline.py, GET /models/status, GET /deployments),
never from this database. There is no local Prometheus or cluster in a
plain local dev setup, so those specific calls keep returning empty /
"offline" no matter what this script seeds. What IS seeded here and WILL
show up: the Model Registry table, the model picker on Monitoring/Drift
(both read GET /admin/deployment-registry), the Overview's model-health
list and recent-tickets widget, and the Remediation page's configs and
trigger history.

Usage:
    export DATABASE_URL='sqlite:////home/hassa/vela/local_test.db'
    python scripts/seed_demo.py
"""

import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _sqlite_path(url: str):
    """Best-effort file path out of a sqlite DATABASE_URL, or None for
    anything else (e.g. postgres) - which this guard doesn't need to cover
    since the committed database is a sqlite file."""
    if not url.startswith("sqlite"):
        return None
    if "sqlite:///" in url:
        return url.split("sqlite:///", 1)[1]
    return url.split("sqlite://", 1)[1]


def _guard_against_app_db():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL is not set - refusing to seed the default app.db.", file=sys.stderr)
        print("Point it at a scratch sqlite file first, e.g.:", file=sys.stderr)
        print("  export DATABASE_URL='sqlite:////home/hassa/vela/local_test.db'", file=sys.stderr)
        sys.exit(1)
    path = _sqlite_path(url)
    if path is not None and os.path.basename(path) == "app.db":
        print(f"ERROR: refusing to seed '{path}' - that's the committed app.db.", file=sys.stderr)
        print("Point DATABASE_URL at a separate scratch database instead.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

# name, display model_name, task_type, model_type, status, days_ago deployed
MODELS = [
    ("fraud-detector-v3", "xgboost-fraud-v3", "fraud-detection", "custom", "online", 52),
    ("churn-predictor", "lightgbm-churn-v2", "tabular-classification", "custom", "online", 38),
    ("sentiment-classifier", "distilbert-base-uncased-finetuned-sst-2-english", "sentiment-analysis", "huggingface", "online", 29),
    ("spam-filter", "mrm8488/bert-tiny-finetuned-sms-spam-detection", "text-classification", "huggingface", "online", 21),
    ("support-ticket-router", "facebook/bart-large-mnli", "zero-shot-classification", "huggingface", "online", 14),
    ("product-recommender", "catboost-recsys-v1", "tabular-classification", "custom", "degraded", 9),
    ("legacy-nps-scorer", "distilbert-base-uncased-finetuned-sst-2-english", "sentiment-analysis", "huggingface", "failed", 61),
]

# deployment name -> (drift_threshold, action_type, target)
DRIFT_CONFIGS = {
    "fraud-detector-v3": (0.50, "github_issue", "org/vela-models"),
    "sentiment-classifier": (0.50, "github_issue", "org/vela-models"),
    "churn-predictor": (0.40, "github_issue", "org/vela-models"),
    "legacy-nps-scorer": (0.45, "webhook", "https://hooks.example.com/nps-alerts"),
}

# deployment name -> [(days_ago, drift_score, status, action_type), ...]
# Only the two genuinely "drifting" models get a trigger history - the
# other two configured-but-stable models (fraud-detector-v3,
# sentiment-classifier) intentionally get none: they've never crossed
# their threshold, which is the realistic way "stable" shows up in this
# schema.
DRIFT_LOGS = {
    "churn-predictor": [
        (20, 0.32, "success", "github_issue"),
        (14, 0.41, "success", "github_issue"),
        (7, 0.53, "failed", "github_issue"),
        (2, 0.61, "success", "github_issue"),
    ],
    "legacy-nps-scorer": [
        (5, 0.72, "success", "webhook"),
        (1, 0.81, "success", "webhook"),
    ],
}

# title, ticket_type, severity, status, deployment name, days_ago filed, days_ago resolved (or None)
TICKETS = [
    ("legacy-nps-scorer failing health checks", "bug", "critical", "open", "legacy-nps-scorer", 1, None),
    ("product-recommender latency degraded after last deploy", "anomaly", "high", "investigating", "product-recommender", 4, None),
    ("Confidence score drift on churn-predictor", "anomaly", "medium", "open", "churn-predictor", 6, None),
    ("False positive spike reported by Risk team", "bug", "medium", "investigating", "fraud-detector-v3", 10, None),
    ("Zero-shot router misclassifying billing tickets", "bug", "low", "resolved", "support-ticket-router", 25, 20),
    ("Spam filter false-negative rate up", "anomaly", "medium", "closed", "spam-filter", 33, 30),
]


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def get_or_create_admin(db, User, create_user):
    admin = db.query(User).filter(User.is_admin == True).first()  # noqa: E712
    if admin:
        return admin
    admin = create_user(
        db, username="admin", name="Administrator", password="admin123",
        is_admin=True, force_password_change=False,
    )
    print("  created admin user 'admin' (password: admin123)")
    return admin


def get_or_create_workspace(db, Workspace, WorkspaceMember, owner):
    ws = db.query(Workspace).filter(Workspace.slug == "ml-platform").first()
    if ws:
        return ws
    ws = Workspace(name="ML Platform", slug="ml-platform", description="Primary workspace for deployed models", owner_id=owner.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    db.add(WorkspaceMember(user_id=owner.id, workspace_id=ws.id, role="admin"))
    db.commit()
    print("  created workspace 'ML Platform'")
    return ws


def get_or_create_team(db, Team, TeamMember, workspace, owner):
    team = db.query(Team).filter(Team.workspace_id == workspace.id, Team.name == "ML Engineering").first()
    if team:
        return team
    team = Team(workspace_id=workspace.id, name="ML Engineering", description="Owns model deployment and monitoring")
    db.add(team)
    db.commit()
    db.refresh(team)
    db.add(TeamMember(team_id=team.id, user_id=owner.id, role="lead"))
    db.commit()
    print("  created team 'ML Engineering'")
    return team


def seed_deployments(db, Deployment, TeamModelPermission, workspace, team, owner, now):
    deployments = {}
    for name, model_name, task_type, model_type, status, days_ago in MODELS:
        existing = db.query(Deployment).filter(Deployment.name == name).first()
        if existing:
            print(f"  skip deployment '{name}' (already exists)")
            deployments[name] = existing
            continue
        dep = Deployment(
            workspace_id=workspace.id,
            name=name,
            model_name=model_name,
            task_type=task_type,
            source="huggingface" if model_type == "huggingface" else "upload",
            status=status,
            model_type=model_type,
            input_type="text",
            is_active=True,
            created_by=owner.id,
            created_at=now - timedelta(days=days_ago, hours=random.randint(0, 20)),
        )
        db.add(dep)
        db.commit()
        db.refresh(dep)
        db.add(TeamModelPermission(team_id=team.id, deployment_id=dep.id, can_predict=True, can_view_metrics=True, granted_by=owner.id))
        db.commit()
        deployments[name] = dep
        print(f"  created deployment '{name}' ({status}, {model_type}, deployed {days_ago}d ago)")
    return deployments


def seed_remediation(db, RemediationConfig, RemediationLog, deployments, workspace, now):
    configs = {}
    for name, (threshold, action_type, target) in DRIFT_CONFIGS.items():
        dep = deployments.get(name)
        if not dep:
            continue
        existing = db.query(RemediationConfig).filter(RemediationConfig.deployment_id == dep.id).first()
        if existing:
            configs[name] = existing
            print(f"  skip remediation config for '{name}' (already exists)")
            continue
        cfg = RemediationConfig(
            deployment_id=dep.id, workspace_id=workspace.id,
            drift_threshold=threshold, action_type=action_type, target=target,
            is_active=True, created_at=now - timedelta(days=45),
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
        configs[name] = cfg
        print(f"  created remediation config for '{name}' (threshold={threshold}, {action_type})")

    for name, entries in DRIFT_LOGS.items():
        dep = deployments.get(name)
        cfg = configs.get(name)
        if not dep or not cfg:
            continue
        existing = db.query(RemediationLog).filter(RemediationLog.deployment_id == dep.id).first()
        if existing:
            print(f"  skip drift log for '{name}' (already exists)")
            continue
        for days_ago, score, status, action_type in entries:
            response = (
                "Issue #482 opened" if status == "success" and action_type == "github_issue"
                else "Webhook delivered (200 OK)" if status == "success"
                else "Delivery failed: connection timed out"
            )
            db.add(RemediationLog(
                config_id=cfg.id, deployment_id=dep.id, drift_score=score,
                action_type=action_type, target=cfg.target, status=status,
                response=response, triggered_at=now - timedelta(days=days_ago),
            ))
        db.commit()
        cfg.last_triggered_at = now - timedelta(days=min(e[0] for e in entries))
        db.commit()
        print(f"  logged {len(entries)} drift trigger(s) for '{name}' (score {entries[0][1]:.2f} -> {entries[-1][1]:.2f})")


def seed_tickets(db, Ticket, deployments, workspace, team, owner, now):
    for title, ttype, severity, status, dep_name, filed_days_ago, resolved_days_ago in TICKETS:
        existing = db.query(Ticket).filter(Ticket.title == title).first()
        if existing:
            print(f"  skip ticket '{title}' (already exists)")
            continue
        dep = deployments.get(dep_name)
        t = Ticket(
            title=title,
            description=f"Demo ticket for {dep_name}: {title.lower()}.",
            ticket_type=ttype, severity=severity, status=status,
            deployment_id=dep.id if dep else None,
            workspace_id=workspace.id, team_id=team.id,
            filed_by=owner.id,
            filed_at=now - timedelta(days=filed_days_ago),
            evidence="",
        )
        if resolved_days_ago is not None:
            t.resolved_by = owner.id
            t.resolved_at = now - timedelta(days=resolved_days_ago)
            t.resolution_note = "Resolved after redeploying with an updated reference window."
        db.add(t)
        db.commit()
        print(f"  filed ticket '{title}' ({status}, {severity})")


def main():
    _guard_against_app_db()

    from backend.app.database import SessionLocal, engine
    from backend.app.db.models import (
        Base, User, Workspace, WorkspaceMember, Team, TeamMember,
        TeamModelPermission, Deployment, RemediationConfig, RemediationLog, Ticket,
    )
    from backend.app.services.auth import create_user

    Base.metadata.create_all(bind=engine)

    now = datetime.utcnow()
    db = SessionLocal()
    try:
        print(f"Seeding {os.environ['DATABASE_URL']}\n")

        print("Users / workspace / team:")
        owner = get_or_create_admin(db, User, create_user)
        workspace = get_or_create_workspace(db, Workspace, WorkspaceMember, owner)
        team = get_or_create_team(db, Team, TeamMember, workspace, owner)

        print("\nDeployments:")
        deployments = seed_deployments(db, Deployment, TeamModelPermission, workspace, team, owner, now)

        print("\nRemediation (drift configs + trigger history):")
        seed_remediation(db, RemediationConfig, RemediationLog, deployments, workspace, now)

        print("\nTickets:")
        seed_tickets(db, Ticket, deployments, workspace, team, owner, now)

        print(f"\nDone. {len(deployments)} models in the registry, admin login: username='{owner.username}'.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
