from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from backend.app.database import SessionLocal
from backend.app.services.auth import decode_token, verify_api_key
from backend.app.db.models import (
    User, WorkspaceMember, Team, TeamMember,
    TeamModelPermission, AccessRequest, Deployment
)
from backend.app.services.teams import (
    create_team, get_workspace_teams, get_user_teams,
    add_team_member, remove_team_member, get_team_members,
    grant_model_access, revoke_model_access, get_team_permissions,
    create_access_request, get_pending_requests, review_access_request
)

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ")[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def require_workspace_admin(workspace_id: int, user: User, db: Session):
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user.id
    ).first()
    if not member or member.role != "admin":
        raise HTTPException(status_code=403, detail="Workspace admin required")
    return member

# ── Team endpoints ──────────────────────────────────────────────────────────

class TeamCreate(BaseModel):
    name: str
    description: str = ""

class MemberAdd(BaseModel):
    user_id: int
    role: str = "member"

class PermissionGrant(BaseModel):
    deployment_id: int
    can_predict: bool = True
    can_view_metrics: bool = False

class AccessRequestCreate(BaseModel):
    workspace_id: int
    team_id: Optional[int] = None
    deployment_id: Optional[int] = None
    message: str = ""

class AccessRequestReview(BaseModel):
    approved: bool
    note: str = ""

@router.post("/workspaces/{workspace_id}/teams")
def create_workspace_team(workspace_id: int, req: TeamCreate,
                           user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_workspace_admin(workspace_id, user, db)
    team = create_team(db, workspace_id, req.name, req.description, user.id)
    return {"id": team.id, "name": team.name, "description": team.description}

@router.get("/workspaces/{workspace_id}/teams")
def list_workspace_teams(workspace_id: int,
                          user=Depends(get_current_user), db: Session = Depends(get_db)):
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user.id
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    teams = get_workspace_teams(db, workspace_id)
    return [{"id": t.id, "name": t.name, "description": t.description, "created_at": t.created_at} for t in teams]

@router.post("/teams/{team_id}/members")
def add_member_to_team(team_id: int, req: MemberAdd,
                        user=Depends(get_current_user), db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    require_workspace_admin(team.workspace_id, user, db)
    member = add_team_member(db, team_id, req.user_id, req.role)
    return {"team_id": team_id, "user_id": req.user_id, "role": member.role}

@router.delete("/teams/{team_id}/members/{user_id}")
def remove_member_from_team(team_id: int, user_id: int,
                              user=Depends(get_current_user), db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    require_workspace_admin(team.workspace_id, user, db)
    success = remove_team_member(db, team_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"message": "Member removed"}

@router.get("/teams/{team_id}/members")
def list_team_members(team_id: int,
                       user=Depends(get_current_user), db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return get_team_members(db, team_id)

@router.post("/teams/{team_id}/permissions")
def grant_team_permission(team_id: int, req: PermissionGrant,
                           user=Depends(get_current_user), db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    # Platform admin, not workspace-role admin (require_workspace_admin) —
    # this is called from /admin/teams-page, which is gated on User.is_admin
    # like every other /admin/* page. require_workspace_admin checks a
    # WorkspaceMember row's role instead, which a platform admin has no
    # guarantee of holding for every workspace a team happens to live in
    # (nothing creates one automatically), so it would 403 admins who are
    # legitimately allowed to be here.
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    perm = grant_model_access(db, team_id, req.deployment_id,
                               req.can_predict, req.can_view_metrics, user.id)
    return {"team_id": team_id, "deployment_id": req.deployment_id,
            "can_predict": perm.can_predict, "can_view_metrics": perm.can_view_metrics}

@router.delete("/teams/{team_id}/permissions/{deployment_id}")
def revoke_team_permission(team_id: int, deployment_id: int,
                            user=Depends(get_current_user), db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    # Same reasoning as grant_team_permission above — must match it, or an
    # admin could grant but not revoke (or vice versa) depending on their
    # incidental WorkspaceMember role in this team's workspace.
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    success = revoke_model_access(db, team_id, deployment_id)
    if not success:
        raise HTTPException(status_code=404, detail="Permission not found")
    return {"message": "Access revoked"}

@router.get("/teams/{team_id}/permissions")
def list_team_permissions(team_id: int,
                           user=Depends(get_current_user), db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return get_team_permissions(db, team_id)

@router.get("/teams/{team_id}")
def get_team(team_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    members = get_team_members(db, team_id)
    permissions = get_team_permissions(db, team_id)
    return {
        "id": team.id,
        "name": team.name,
        "description": team.description,
        "workspace_id": team.workspace_id,
        "members": members,
        "permissions": permissions
    }

# ── Access Request endpoints ────────────────────────────────────────────────

@router.post("/access-requests")
def request_access(req: AccessRequestCreate,
                   user=Depends(get_current_user), db: Session = Depends(get_db)):
    access_req = create_access_request(
        db, user.id, req.workspace_id, req.team_id, req.deployment_id, req.message
    )
    return {
        "id": access_req.id,
        "status": access_req.status,
        "message": "Access request submitted. An admin will review it."
    }

@router.get("/workspaces/{workspace_id}/access-requests")
def list_access_requests(workspace_id: int,
                          user=Depends(get_current_user), db: Session = Depends(get_db)):
    require_workspace_admin(workspace_id, user, db)
    return get_pending_requests(db, workspace_id)

@router.post("/access-requests/{request_id}/review")
def review_request(request_id: int, req: AccessRequestReview,
                   user=Depends(get_current_user), db: Session = Depends(get_db)):
    access_req = db.query(AccessRequest).filter(AccessRequest.id == request_id).first()
    if not access_req:
        raise HTTPException(status_code=404, detail="Request not found")
    require_workspace_admin(access_req.workspace_id, user, db)
    result = review_access_request(db, request_id, user.id, req.approved, req.note)
    return {
        "id": result.id,
        "status": result.status,
        "message": f"Request {'approved' if req.approved else 'denied'}"
    }

@router.get("/users/me/teams")
def my_teams(user=Depends(get_current_user), db: Session = Depends(get_db)):
    memberships = db.query(TeamMember).filter(TeamMember.user_id == user.id).all()
    team_ids = [m.team_id for m in memberships]
    if not team_ids:
        return []
    teams = db.query(Team).filter(Team.id.in_(team_ids)).all()
    result = []
    for t in teams:
        member_count = db.query(TeamMember).filter(TeamMember.team_id == t.id).count()
        model_count = db.query(TeamModelPermission).filter(TeamModelPermission.team_id == t.id).count()
        result.append({
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "workspace_id": t.workspace_id,
            "member_count": member_count,
            "model_count": model_count,
        })
    return result

@router.get("/users/me/access-requests")
def my_access_requests(user=Depends(get_current_user), db: Session = Depends(get_db)):
    requests = db.query(AccessRequest).filter(AccessRequest.user_id == user.id).all()
    return [{
        "id": r.id,
        "workspace_id": r.workspace_id,
        "team_id": r.team_id,
        "deployment_id": r.deployment_id,
        "status": r.status,
        "message": r.message,
        "created_at": r.created_at,
        "review_note": r.review_note
    } for r in requests]
