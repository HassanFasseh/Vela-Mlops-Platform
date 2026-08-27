import traceback
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
from backend.app.db.models import WorkspaceMember, WorkspaceApiKey, ModelCard, Deployment, User, Workspace, Team

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
    team_id: Optional[int] = None
    deployment_id: Optional[int] = None

class ModelCardCreate(BaseModel):
    # Optional[...] = None (not a "" default) so create_model_card can
    # tell "field omitted, leave whatever's already there alone" apart
    # from "field explicitly cleared to blank" on an update — the docs.js
    # form only ever sends dataset/dataset_source/license/
    # performance_notes/limitations, and must not wipe description/
    # dataset_size/tags on an existing card just because it doesn't know
    # about them (those are only ever set via the legacy /workspace/{id}
    # "Document a model" form, which still sends the full set).
    deployment_id: int
    description: Optional[str] = None
    dataset: Optional[str] = None
    dataset_source: Optional[str] = None
    dataset_size: Optional[str] = None
    license: Optional[str] = None
    tags: Optional[str] = None
    performance_notes: Optional[str] = None
    limitations: Optional[str] = None

# Auth endpoints handled in main.py
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
    # This endpoint was 500ing with nothing in the logs — the exception was
    # happening somewhere inside FastAPI's default unhandled-exception path,
    # which returns a bare "Internal Server Error" to the client and prints
    # nothing of its own. Logging explicitly here, at both the membership
    # check and around the whole body, so the actual traceback shows up in
    # the server log (matches this codebase's print(..., flush=True) style
    # used everywhere else — services/remediation.py, model-service, etc —
    # rather than introducing the logging module just for this one route).
    try:
        try:
            member_check = db.query(WorkspaceMember).filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id
            ).first()
        except Exception:
            print(f"[api-keys] workspace membership check failed — user_id={user.id} workspace_id={workspace_id}", flush=True)
            traceback.print_exc()
            raise

        if not member_check or member_check.role not in ["admin", "member"]:
            raise HTTPException(status_code=403, detail="Not authorized")

        raw_key, api_key = generate_api_key(db, workspace_id, req.name, req.team_id, req.deployment_id)
        return {
            "key": raw_key,
            "prefix": api_key.key_prefix,
            "name": api_key.name,
            "team_id": api_key.team_id,
            "deployment_id": api_key.deployment_id,
            "warning": "Copy this key now — it will not be shown again"
        }
    except HTTPException:
        raise
    except Exception:
        print(f"[api-keys] create_api_key failed — user_id={user.id} workspace_id={workspace_id} name={req.name!r}", flush=True)
        traceback.print_exc()
        raise

@router.get("/workspaces/{workspace_id}/api-keys")
def list_api_keys(workspace_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    keys = db.query(WorkspaceApiKey).filter(
        WorkspaceApiKey.workspace_id == workspace_id,
        WorkspaceApiKey.is_active == True
    ).all()
    result = []
    for k in keys:
        team = db.query(Team).filter(Team.id == k.team_id).first() if k.team_id else None
        dep = db.query(Deployment).filter(Deployment.id == k.deployment_id).first() if k.deployment_id else None
        result.append({
            "id": k.id,
            "name": k.name,
            "prefix": k.key_prefix,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at,
            "team_id": k.team_id,
            "team_name": team.name if team else None,
            "deployment_id": k.deployment_id,
            "model_name": dep.model_name if dep else None,
            "deployment_name": dep.name if dep else None,
        })
    return result

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

_MODEL_CARD_FIELDS = ("description", "dataset", "dataset_source", "dataset_size", "license", "tags", "performance_notes", "limitations")

@router.post("/model-cards")
def create_model_card(req: ModelCardCreate, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Create-or-update, keyed by deployment_id — one model card per
    deployment. Lets /admin/docs offer a single "create or edit" form
    inline (see docs.js) instead of needing a separate PATCH endpoint."""
    deployment = db.query(Deployment).filter(Deployment.id == req.deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    card = db.query(ModelCard).filter(ModelCard.deployment_id == req.deployment_id).first()
    if card:
        for f in _MODEL_CARD_FIELDS:
            value = getattr(req, f)
            if value is not None:
                setattr(card, f, value)
    else:
        card = ModelCard(
            deployment_id=req.deployment_id,
            workspace_id=deployment.workspace_id,
            created_by=user.id,
            **{f: (getattr(req, f) or "") for f in _MODEL_CARD_FIELDS},
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
        "dataset_source": card.dataset_source,
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

  <h2>Upload your own model</h2>
  <div class="card">
    <input type="text" id="upload-model-name" placeholder="Model name (e.g. my-sentiment-model-v1)">
    <input type="file" id="upload-file" accept=".bin,.pt,.pkl,.safetensors,.h5,.onnx" style="margin:.5rem 0;color:#888">
    <button onclick="uploadModel()">Upload model</button>
    <div id="upload-progress" style="font-size:.8rem;color:#888;margin-top:.3rem"></div>
  </div>
  <div id="uploaded-models"></div>

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
  loadUploadedModels();

  async function loadUploadedModels(){{
    const keys = await fetch('/workspaces/'+WS_ID+'/api-keys',{{headers:H}});
    const keyList = await keys.json();
    if(!keyList.length) return;
    const apiKey = keyList[0].prefix + '...';
    const el = document.getElementById('uploaded-models');

    // Use first key prefix for display only — real upload uses stored key
    const r = await fetch('/api/v1/workspace/'+WS_ID+'/models', {{
      headers: {{...H}}
    }});
    // Note: this endpoint needs API key not JWT — skip for now, show placeholder
    el.innerHTML = '<div style="color:#555;font-size:.8rem;padding:.3rem 0">Use the API to list uploaded models: GET /api/v1/workspace/'+WS_ID+'/models with X-API-Key header</div>';
  }}

  async function uploadModel(){{
    const name = document.getElementById('upload-model-name').value.trim();
    const file = document.getElementById('upload-file').files[0];
    const progress = document.getElementById('upload-progress');
    if(!name || !file){{ progress.textContent='Please enter a model name and select a file.'; return; }}

    // Get API key for upload
    const keysR = await fetch('/workspaces/'+WS_ID+'/api-keys',{{headers:H}});
    const keysList = await keysR.json();
    if(!keysList.length){{ progress.textContent='Generate an API key first.'; return; }}

    // We need the raw key — prompt user
    const rawKey = prompt('Enter your full API key (shown when generated):');
    if(!rawKey){{ progress.textContent='API key required for upload.'; return; }}

    progress.textContent = 'Uploading '+file.name+' ('+Math.round(file.size/1024/1024*10)/10+' MB)...';

    const form = new FormData();
    form.append('file', file);
    form.append('model_name', name);
    form.append('workspace_id', WS_ID);

    const r = await fetch('/api/v1/upload-model', {{
      method: 'POST',
      headers: {{'X-API-Key': rawKey}},
      body: form
    }});
    const d = await r.json();
    if(r.ok){{
      progress.textContent = 'Uploaded successfully! Deployment ID: '+d.deployment_id+' ('+d.size_mb+' MB)';
    }} else {{
      progress.textContent = 'Error: '+(d.detail||JSON.stringify(d));
    }}
  }}
</script>
</body></html>"""
