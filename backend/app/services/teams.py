from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
from backend.app.db.models import (
    Team, TeamMember, TeamModelPermission, AccessRequest,
    WorkspaceApiKey, Deployment, WorkspaceMember, User
)

# ── Teams ──────────────────────────────────────────────────────────────────

def create_team(db: Session, workspace_id: int, name: str, description: str, creator_id: int) -> Team:
    team = Team(workspace_id=workspace_id, name=name, description=description)
    db.add(team)
    db.commit()
    db.refresh(team)
    # Creator becomes team lead automatically
    member = TeamMember(team_id=team.id, user_id=creator_id, role="lead")
    db.add(member)
    db.commit()
    return team

def get_workspace_teams(db: Session, workspace_id: int) -> list:
    return db.query(Team).filter(Team.workspace_id == workspace_id).all()

def get_user_teams(db: Session, user_id: int, workspace_id: int) -> list:
    memberships = db.query(TeamMember).filter(TeamMember.user_id == user_id).all()
    team_ids = [m.team_id for m in memberships]
    return db.query(Team).filter(
        Team.id.in_(team_ids),
        Team.workspace_id == workspace_id
    ).all()

def add_team_member(db: Session, team_id: int, user_id: int, role: str = "member") -> TeamMember:
    existing = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.user_id == user_id
    ).first()
    if existing:
        member = existing
    else:
        member = TeamMember(team_id=team_id, user_id=user_id, role=role)
        db.add(member)
        db.commit()
        db.refresh(member)

    # A team member needs workspace access to do anything workspace-scoped
    # (generate API keys, etc — see /app/api-keys). Admin-created users
    # start with zero WorkspaceMember rows, and there's no self-service
    # path for a member to fix that themselves. If they have no workspace
    # membership anywhere, drop them into this team's own workspace — it
    # already exists (every Team has a workspace_id) and is the one place
    # that's actually relevant to what they were just added to. Runs even
    # when the TeamMember row already existed, so it also repairs anyone
    # who got added before this existed.
    has_workspace = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user_id
    ).first()
    if not has_workspace:
        team = db.query(Team).filter(Team.id == team_id).first()
        if team:
            db.add(WorkspaceMember(user_id=user_id, workspace_id=team.workspace_id, role="member"))
            db.commit()

    return member

def remove_team_member(db: Session, team_id: int, user_id: int) -> bool:
    member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.user_id == user_id
    ).first()
    if not member:
        return False
    db.delete(member)
    db.commit()
    return True

def get_team_members(db: Session, team_id: int) -> list:
    members = db.query(TeamMember).filter(TeamMember.team_id == team_id).all()
    result = []
    for m in members:
        user = db.query(User).filter(User.id == m.user_id).first()
        result.append({
            "user_id": m.user_id,
            "email": user.email if user else "",
            "name": user.name if user else "",
            "role": m.role,
            "joined_at": m.joined_at
        })
    return result

# ── Model Permissions ──────────────────────────────────────────────────────

def grant_model_access(db: Session, team_id: int, deployment_id: int,
                        can_predict: bool = True, can_view_metrics: bool = False,
                        granted_by: int = None) -> TeamModelPermission:
    existing = db.query(TeamModelPermission).filter(
        TeamModelPermission.team_id == team_id,
        TeamModelPermission.deployment_id == deployment_id
    ).first()
    if existing:
        existing.can_predict = can_predict
        existing.can_view_metrics = can_view_metrics
        db.commit()
        return existing
    perm = TeamModelPermission(
        team_id=team_id,
        deployment_id=deployment_id,
        can_predict=can_predict,
        can_view_metrics=can_view_metrics,
        granted_by=granted_by
    )
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return perm

def revoke_model_access(db: Session, team_id: int, deployment_id: int) -> bool:
    perm = db.query(TeamModelPermission).filter(
        TeamModelPermission.team_id == team_id,
        TeamModelPermission.deployment_id == deployment_id
    ).first()
    if not perm:
        return False
    db.delete(perm)
    db.commit()
    return True

def get_team_permissions(db: Session, team_id: int) -> list:
    perms = db.query(TeamModelPermission).filter(
        TeamModelPermission.team_id == team_id
    ).all()
    result = []
    for p in perms:
        dep = db.query(Deployment).filter(Deployment.id == p.deployment_id).first()
        result.append({
            "deployment_id": p.deployment_id,
            "deployment_name": dep.name if dep else "unknown",
            "model_name": dep.model_name if dep else "unknown",
            "can_predict": p.can_predict,
            "can_view_metrics": p.can_view_metrics,
            "granted_at": p.granted_at
        })
    return result

def check_team_model_permission(db: Session, api_key: WorkspaceApiKey, deployment_id: int) -> bool:
    """Check if an API key has permission to predict against a specific deployment."""
    # If key is not team-scoped, allow all workspace models
    if not api_key.team_id:
        return True
    # If key is deployment-scoped, check exact match
    if api_key.deployment_id:
        return api_key.deployment_id == deployment_id
    # Check team permission
    perm = db.query(TeamModelPermission).filter(
        TeamModelPermission.team_id == api_key.team_id,
        TeamModelPermission.deployment_id == deployment_id,
        TeamModelPermission.can_predict == True
    ).first()
    return perm is not None

# ── Access Requests ────────────────────────────────────────────────────────

def create_access_request(db: Session, user_id: int, workspace_id: int,
                           team_id: int = None, deployment_id: int = None,
                           message: str = "") -> AccessRequest:
    # Check not already pending
    existing = db.query(AccessRequest).filter(
        AccessRequest.user_id == user_id,
        AccessRequest.workspace_id == workspace_id,
        AccessRequest.status == "pending"
    ).first()
    if existing:
        return existing
    req = AccessRequest(
        user_id=user_id,
        workspace_id=workspace_id,
        team_id=team_id,
        deployment_id=deployment_id,
        message=message
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req

def get_pending_requests(db: Session, workspace_id: int) -> list:
    requests = db.query(AccessRequest).filter(
        AccessRequest.workspace_id == workspace_id,
        AccessRequest.status == "pending"
    ).all()
    result = []
    for r in requests:
        user = db.query(User).filter(User.id == r.user_id).first()
        dep = db.query(Deployment).filter(Deployment.id == r.deployment_id).first() if r.deployment_id else None
        team = db.query(Team).filter(Team.id == r.team_id).first() if r.team_id else None
        result.append({
            "id": r.id,
            "user_id": r.user_id,
            "user_email": user.email if user else "",
            "user_name": user.name if user else "",
            "team_id": r.team_id,
            "team_name": team.name if team else None,
            "deployment_id": r.deployment_id,
            "deployment_name": dep.name if dep else None,
            "message": r.message,
            "created_at": r.created_at
        })
    return result

def review_access_request(db: Session, request_id: int, reviewer_id: int,
                           approved: bool, note: str = "") -> AccessRequest:
    req = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not req:
        return None
    req.status = "approved" if approved else "denied"
    req.reviewed_by = reviewer_id
    req.reviewed_at = datetime.utcnow()
    req.review_note = note
    if approved:
        # Auto-add user to workspace and team if approved
        existing_ws = db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == req.workspace_id,
            WorkspaceMember.user_id == req.user_id
        ).first()
        if not existing_ws:
            ws_member = WorkspaceMember(
                user_id=req.user_id,
                workspace_id=req.workspace_id,
                role="viewer"
            )
            db.add(ws_member)
        if req.team_id:
            existing_tm = db.query(TeamMember).filter(
                TeamMember.team_id == req.team_id,
                TeamMember.user_id == req.user_id
            ).first()
            if not existing_tm:
                tm = TeamMember(team_id=req.team_id, user_id=req.user_id, role="member")
                db.add(tm)
    db.commit()
    db.refresh(req)
    return req
