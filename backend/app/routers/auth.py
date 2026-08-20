from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from backend.app.database import SessionLocal
from backend.app.services.auth import (
    create_user, authenticate_user, create_access_token,
    decode_token, create_workspace, get_user_workspaces,
    generate_api_key, verify_api_key, get_user_by_email
)
from backend.app.db.models import WorkspaceMember, WorkspaceApiKey, ModelCard, Deployment, User, Workspace

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

class SignupRequest(BaseModel):
    email: str
    name: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class WorkspaceCreate(BaseModel):
    name: str
    description: str = ""

class ApiKeyCreate(BaseModel):
    name: str

class ModelCardCreate(BaseModel):
    deployment_id: int
    description: str = ""
    dataset: str = ""
    dataset_size: str = ""
    license: str = ""
    tags: str = ""
    performance_notes: str = ""
    limitations: str = ""

@router.post("/auth/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    try:
        if get_user_by_email(db, req.email):
            raise HTTPException(status_code=400, detail="Email already registered")
        user = create_user(db, req.email, req.name, req.password)
        token = create_access_token(user.id, user.email)
        return {"token": token, "user": {"id": user.id, "email": user.email, "name": user.name}}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)} | {traceback.format_exc()[-300:]}")

@router.post("/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user.id, user.email)
    return {"token": token, "user": {"id": user.id, "email": user.email, "name": user.name}}

@router.get("/auth/me")
def me(user=Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "name": user.name}

@router.post("/workspaces")
def create_ws(req: WorkspaceCreate, user=Depends(get_current_user), db: Session = Depends(get_db)):
    ws = create_workspace(db, req.name, req.description, user)
    return {"id": ws.id, "name": ws.name, "slug": ws.slug, "description": ws.description}

@router.get("/workspaces")
def list_workspaces(user=Depends(get_current_user), db: Session = Depends(get_db)):
    workspaces = get_user_workspaces(db, user.id)
    return [{"id": w.id, "name": w.name, "slug": w.slug, "description": w.description} for w in workspaces]

@router.get("/workspaces/{workspace_id}/members")
def list_members(workspace_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    members = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace_id).all()
    result = []
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        result.append({"user_id": m.user_id, "email": u.email if u else "", "name": u.name if u else "", "role": m.role})
    return result

@router.post("/workspaces/{workspace_id}/invite")
def invite_member(workspace_id: int, email: str, role: str = "member", user=Depends(get_current_user), db: Session = Depends(get_db)):
    member_check = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user.id
    ).first()
    if not member_check or member_check.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can invite members")
    invitee = get_user_by_email(db, email)
    if not invitee:
        raise HTTPException(status_code=404, detail="User not found — they must sign up first")
    existing = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == invitee.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already a member")
    member = WorkspaceMember(user_id=invitee.id, workspace_id=workspace_id, role=role)
    db.add(member)
    db.commit()
    return {"message": f"{email} added to workspace"}

@router.post("/workspaces/{workspace_id}/api-keys")
def create_api_key(workspace_id: int, req: ApiKeyCreate, user=Depends(get_current_user), db: Session = Depends(get_db)):
    member_check = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user.id
    ).first()
    if not member_check or member_check.role not in ["admin", "member"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    raw_key, api_key = generate_api_key(db, workspace_id, req.name)
    return {
        "key": raw_key,
        "prefix": api_key.key_prefix,
        "name": api_key.name,
        "warning": "Copy this key now — it will not be shown again"
    }

@router.get("/workspaces/{workspace_id}/api-keys")
def list_api_keys(workspace_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    keys = db.query(WorkspaceApiKey).filter(
        WorkspaceApiKey.workspace_id == workspace_id,
        WorkspaceApiKey.is_active == True
    ).all()
    return [{"id": k.id, "name": k.name, "prefix": k.key_prefix, "created_at": k.created_at, "last_used_at": k.last_used_at} for k in keys]

@router.delete("/workspaces/{workspace_id}/api-keys/{key_id}")
def revoke_api_key(workspace_id: int, key_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    key = db.query(WorkspaceApiKey).filter(
        WorkspaceApiKey.id == key_id,
        WorkspaceApiKey.workspace_id == workspace_id
    ).first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    key.is_active = False
    db.commit()
    return {"message": "Key revoked"}

@router.post("/model-cards")
def create_model_card(req: ModelCardCreate, user=Depends(get_current_user), db: Session = Depends(get_db)):
    deployment = db.query(Deployment).filter(Deployment.id == req.deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    card = ModelCard(
        deployment_id=req.deployment_id,
        workspace_id=deployment.workspace_id,
        description=req.description,
        dataset=req.dataset,
        dataset_size=req.dataset_size,
        license=req.license,
        tags=req.tags,
        performance_notes=req.performance_notes,
        limitations=req.limitations,
        created_by=user.id
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return {"id": card.id, "message": f"Model card saved successfully (ID: {card.id})"}

@router.get("/model-cards/{deployment_id}")
def get_model_card(deployment_id: int, db: Session = Depends(get_db)):
    card = db.query(ModelCard).filter(ModelCard.deployment_id == deployment_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="No model card found")
    return {
        "deployment_id": card.deployment_id,
        "description": card.description,
        "dataset": card.dataset,
        "dataset_size": card.dataset_size,
        "license": card.license,
        "tags": card.tags,
        "performance_notes": card.performance_notes,
        "limitations": card.limitations,
        "created_at": card.created_at
    }

@router.get("/workspace/{workspace_id}", response_class=HTMLResponse)
def workspace_dashboard(workspace_id: int, db: Session = Depends(get_db)):
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    ws_name = ws.name if ws else f"Workspace {workspace_id}"
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>{ws_name}</title>
<style>
  body{{font-family:monospace;background:#0a0a0f;color:#e0e0e0;padding:2rem;max-width:900px;margin:0 auto}}
  h1{{color:#7eb8f7;border-bottom:1px solid #222;padding-bottom:.5rem}}
  .card{{background:#111;border:1px solid #222;border-radius:8px;padding:1rem;margin:.5rem 0}}
  input,textarea{{background:#0a0a0f;border:1px solid #333;color:#e0e0e0;padding:.4rem .6rem;border-radius:4px;font-family:monospace;width:100%;margin:.3rem 0;box-sizing:border-box}}
  button{{background:#1a3a5c;color:#7eb8f7;border:1px solid #2a5a8c;padding:.4rem 1rem;border-radius:4px;cursor:pointer;font-family:monospace}}
  button:hover{{background:#2a5a8c}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:3px;font-size:.75rem;background:#1a3a1a;color:#7ef7a0}}
  h2{{font-size:.85rem;color:#555;text-transform:uppercase;letter-spacing:.1em;margin:1.5rem 0 .5rem}}
  .back{{color:#555;font-size:.8rem;cursor:pointer;margin-bottom:1rem;display:inline-block}}
  .back:hover{{color:#7eb8f7}}
  code{{background:#1a1a2a;padding:2px 6px;border-radius:3px;font-size:.85rem;word-break:break-all}}
</style></head>
<body>
  <span class="back" onclick="window.location.href='/workspaces-page'">&larr; All workspaces</span>
  <h1>&#9881; {ws_name}</h1>

  <h2>API Keys</h2>
  <div class="card">
    <input type="text" id="key-name" placeholder="Key name (e.g. production, ci-cd)">
    <button onclick="createKey()">Generate API key</button>
    <div id="key-result" style="margin-top:.5rem;font-size:.8rem;color:#7ef7a0;word-break:break-all"></div>
  </div>
  <div id="keys-list"></div>

  <h2>Members</h2>
  <div class="card">
    <input type="email" id="invite-email" placeholder="Email to invite">
    <button onclick="inviteMember()">Invite member</button>
    <div id="invite-status" style="font-size:.8rem;color:#888;margin-top:.3rem"></div>
  </div>
  <div id="members-list"></div>

  <h2>Document a model</h2>
  <div class="card">
    <input type="number" id="mc-dep-id" placeholder="Deployment ID">
    <textarea id="mc-desc" rows="2" placeholder="What does this model do?"></textarea>
    <textarea id="mc-dataset" rows="2" placeholder="Dataset used for training"></textarea>
    <input type="text" id="mc-size" placeholder="Dataset size (e.g. 50k examples)">
    <input type="text" id="mc-license" placeholder="License (e.g. MIT, Apache 2.0)">
    <input type="text" id="mc-tags" placeholder="Tags (comma-separated)">
    <textarea id="mc-perf" rows="2" placeholder="Performance notes"></textarea>
    <textarea id="mc-limits" rows="2" placeholder="Known limitations"></textarea>
    <button onclick="saveCard()">Save model card</button>
    <div id="mc-status" style="font-size:.8rem;color:#888;margin-top:.3rem"></div>
  </div>

<script>
  const WS_ID = {workspace_id};
  const token = localStorage.getItem('aodp_token');
  if(!token) window.location.href = '/auth/login-page';
  const H = {{'Content-Type':'application/json','Authorization':'Bearer '+token}};

  async function loadKeys(){{
    const r = await fetch('/workspaces/'+WS_ID+'/api-keys',{{headers:H}});
    const keys = await r.json();
    document.getElementById('keys-list').innerHTML = keys.length
      ? keys.map(k=>'<div class="card" style="display:flex;justify-content:space-between;align-items:center"><span><b>'+k.name+'</b> &nbsp;<code>'+k.prefix+'...</code></span><button onclick="revokeKey('+k.id+')">Revoke</button></div>').join('')
      : '<div style="color:#555;font-size:.85rem;padding:.5rem 0">No keys yet</div>';
  }}

  async function createKey(){{
    const name=document.getElementById('key-name').value.trim();
    if(!name) return;
    const r=await fetch('/workspaces/'+WS_ID+'/api-keys',{{method:'POST',headers:H,body:JSON.stringify({{name}})}});
    const d=await r.json();
    document.getElementById('key-result').innerHTML='<b>Copy now — shown once:</b><br><code>'+d.key+'</code>';
    loadKeys();
  }}

  async function revokeKey(id){{
    await fetch('/workspaces/'+WS_ID+'/api-keys/'+id,{{method:'DELETE',headers:H}});
    loadKeys();
  }}

  async function loadMembers(){{
    const r=await fetch('/workspaces/'+WS_ID+'/members',{{headers:H}});
    const members=await r.json();
    document.getElementById('members-list').innerHTML=members.map(m=>
      '<div class="card">'+m.name+' ('+m.email+') &nbsp;<span class="badge">'+m.role+'</span></div>'
    ).join('');
  }}

  async function inviteMember(){{
    const email=document.getElementById('invite-email').value.trim();
    if(!email) return;
    const r=await fetch('/workspaces/'+WS_ID+'/invite?email='+encodeURIComponent(email),{{method:'POST',headers:H}});
    const d=await r.json();
    document.getElementById('invite-status').textContent=d.message||d.detail;
    loadMembers();
  }}

  async function saveCard(){{
    const body={{
      deployment_id:parseInt(document.getElementById('mc-dep-id').value),
      description:document.getElementById('mc-desc').value,
      dataset:document.getElementById('mc-dataset').value,
      dataset_size:document.getElementById('mc-size').value,
      license:document.getElementById('mc-license').value,
      tags:document.getElementById('mc-tags').value,
      performance_notes:document.getElementById('mc-perf').value,
      limitations:document.getElementById('mc-limits').value,
    }};
    const r=await fetch('/model-cards',{{method:'POST',headers:H,body:JSON.stringify(body)}});
    const d=await r.json();
    document.getElementById('mc-status').textContent=d.message||d.detail;
  }}

  loadKeys();
  loadMembers();
</script>
</body></html>"""
