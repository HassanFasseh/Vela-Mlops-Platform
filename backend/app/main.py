import fastapi
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from backend.app.schemas import Model
from backend.app.db.models import Base
from backend.app.database import engine
from backend.app.services.deployment import deploy_model
from backend.app.services.timeline import build_timeline, build_metrics_summary
from backend.app.services.summary import generate_summary
from pydantic import BaseModel
from typing import Optional
import requests as http_requests
import os

Base.metadata.create_all(bind=engine)

from contextlib import asynccontextmanager
import asyncio

async def remediation_loop():
    """Check drift and fire remediations every 5 minutes."""
    while True:
        try:
            from backend.app.database import SessionLocal
            from backend.app.services.remediation import check_and_fire
            db = SessionLocal()
            check_and_fire(db)
            db.close()
        except Exception as e:
            print(f"[remediation] loop error: {e}", flush=True)
        await asyncio.sleep(300)  # 5 minutes

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(remediation_loop())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

def get_verified_user(authorization: str, db=None):
    """Get current user and enforce force_password_change."""
    from backend.app.services.auth import decode_token
    from backend.app.db.models import User
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    from backend.app.database import SessionLocal
    close_db = db is None
    if db is None:
        db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        if user.force_password_change:
            raise HTTPException(
                status_code=403,
                detail="Password change required",
                headers={"X-Force-Password-Change": "true"}
            )
        return user, db
    finally:
        if close_db:
            db.close()



from backend.app.routers.auth import router as auth_router
from backend.app.routers.teams import router as teams_router
from backend.app.routers.admin_pages import router as admin_pages_router
from backend.app.routers.member_pages import router as member_pages_router
app.include_router(auth_router)
app.include_router(teams_router)
app.include_router(admin_pages_router)
app.include_router(member_pages_router)


@app.get("/metrics-summary")
def metrics_summary(job: str = "model-service", pod: str = None, deployment_id: int = None):
    return build_metrics_summary(job, pod, deployment_id)

import os
MODEL_SERVICE_URL   = os.environ.get("MODEL_SERVICE_URL", "http://model-service.default.svc.cluster.local")
MODEL_SERVICE_2_URL = os.environ.get("MODEL_SERVICE_2_URL", "http://model-service-2.default.svc.cluster.local")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")

class PredictRequest(BaseModel):
    # Shared by /predict-proxy (model_id/service_name routing, no
    # deployment_id concept) and /api/v1/predict (deployment_id-routed,
    # input shaped by the deployment's own input_type) — a superset of
    # both rather than two models, so /predict-proxy keeps working
    # unchanged. text/data/file are all optional here at the schema
    # level; /api/v1/predict enforces which one is actually required
    # per-request based on the target deployment's input_type.
    text: Optional[str] = None
    data: Optional[dict] = None
    file: Optional[str] = None  # base64-encoded
    model_id: int = 0
    service_name: str = ""
    deployment_id: int = None
    labels: list[str] = ["technology", "sports", "politics", "entertainment", "business"]

class DeployModelRequest(BaseModel):
    model_name: str
    task_type: str
    deployment_name: str

@app.get("/", response_class=HTMLResponse)
def root():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vela — Self-hosted MLOps</title>
<style>
  :root{
    --bg:#f7f6f3; --ink:#0a0a0f; --sub:#5c5c66; --line:#d8d6cf;
    --accent:#2b5a8a; --accent-soft:#2b5a8a55; --teal:#0d9aa6;
  }
  *{box-sizing:border-box}
  html,body{height:100%;margin:0;overflow:hidden}
  body{
    font-family:ui-monospace,"JetBrains Mono","SFMono-Regular",Menlo,Consolas,monospace;
    background:var(--bg); color:var(--ink);
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    position:relative;
  }
  /* subtle technical grid */
  .grid{position:absolute; inset:0; opacity:.5;
    background-image:
      linear-gradient(var(--line) 1px, transparent 1px),
      linear-gradient(90deg, var(--line) 1px, transparent 1px);
    background-size:56px 56px;
    -webkit-mask-image:radial-gradient(ellipse at 50% 40%, #000 0%, transparent 72%);
            mask-image:radial-gradient(ellipse at 50% 40%, #000 0%, transparent 72%);
  }
  /* Constellation — a live canvas network (not SVG): nodes drift in random
     directions, bounce off the viewport edges, and connect to nearby
     nodes as they pass within range, like a star chart or a shipping
     network used for navigation. Rendered/animated in the script below;
     this just sizes and dims the canvas. */
  .graphic{position:absolute; inset:0; display:block; width:100%; height:100%; opacity:.35; pointer-events:none}

  /* Waves — a slow, seamless horizontal scroll built from a path that
     repeats every 1200 units inside a 2400-wide viewBox; translating by
     exactly -50% loops it with no visible seam. Real ocean-wave amplitude,
     saturated teal — an accent that actually reads as water, not a
     hairline gradient. */
  .waves{position:absolute; left:0; right:0; bottom:0; height:180px; overflow:hidden; pointer-events:none}
  .wave{position:absolute; bottom:0; left:0; width:200%; height:100%; animation:wave-scroll linear infinite}
  .wave-back{fill:var(--accent); opacity:.18; animation-duration:32s}
  .wave-front{fill:var(--teal); opacity:.4; animation-duration:20s}
  @keyframes wave-scroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}
  @media (prefers-reduced-motion: reduce){.wave{animation:none}}

  main{position:relative; z-index:1; text-align:center; padding:0 1.5rem; max-width:640px}
  .wordmark{
    display:flex; align-items:center; justify-content:center; gap:.5rem;
    font-size:clamp(2.2rem, 6vw, 3.4rem); font-weight:800; letter-spacing:.02em;
    margin:0 0 .9rem;
  }
  .sail-icon{width:1.25em; height:1.25em; flex-shrink:0}
  .tagline{font-size:clamp(.85rem,1.6vw,1rem); color:var(--sub); line-height:1.7; margin:0 0 1.6rem}
  /* Headline — 40% larger than the tagline it sits under, bold, and a
     left-to-right ink-to-accent gradient rather than a flat color. */
  .tagline .headline{
    display:inline-block; margin-top:.35rem;
    font-size:clamp(1.19rem, 2.24vw, 1.4rem); font-weight:800;
    background:linear-gradient(90deg, #0f172a, #0ea5e9);
    -webkit-background-clip:text; background-clip:text;
    color:transparent; -webkit-text-fill-color:transparent;
  }
  .cta-row{display:flex; gap:1rem; align-items:center; justify-content:center; flex-wrap:wrap}
  .btn-primary{
    background:var(--ink); color:#fff; border:1px solid var(--ink);
    padding:.65rem 1.4rem; border-radius:6px; font:inherit; font-size:.85rem; font-weight:600;
    text-decoration:none; cursor:pointer; letter-spacing:.02em;
  }
  .btn-primary:hover{background:#232330}
  .link-secondary{color:var(--accent); font-size:.82rem; text-decoration:none; border-bottom:1px solid transparent}
  .link-secondary:hover{border-bottom-color:var(--accent)}

  /* Terminal — a small "instrument" showing Vela actually doing things:
     a deploy, then a drift detection + explanation cycle, looping. */
  .terminal{
    margin:1.5rem auto 0; text-align:left; width:100%; max-width:460px;
    background:#0a0a0f; border:1px solid #1e1e2e; border-radius:10px;
    box-shadow:0 16px 36px rgba(10,10,15,.16); overflow:hidden;
  }
  .terminal-bar{
    display:flex; align-items:center; gap:.35rem;
    padding:.5rem .7rem; background:#111119; border-bottom:1px solid #1e1e2e;
  }
  .term-dot{width:8px; height:8px; border-radius:50%}
  .term-dot.r{background:#f77e7e} .term-dot.y{background:#f7c97e} .term-dot.g{background:#7ef7a0}
  .terminal-title{margin-left:.45rem; font-size:.66rem; color:#6b6b78; letter-spacing:.02em}
  .terminal-body{
    padding:.75rem .9rem; height:150px; overflow:hidden;
    font-size:.7rem; line-height:1.7; color:#c7cfe0; text-align:left;
  }
  .term-line{white-space:pre-wrap; word-break:break-word; margin:0}
  .term-line.cmd{color:#7eb8f7}
  .term-line.ok{color:#7ef7a0}
  .term-cursor{
    display:inline-block; width:6px; height:.9em; margin-left:1px;
    background:#38bdf8; vertical-align:text-bottom;
    animation:term-blink 1s step-end infinite;
  }
  @keyframes term-blink{50%{opacity:0}}
  @media (prefers-reduced-motion: reduce){.term-cursor{animation:none}}

  footer{
    position:absolute; bottom:0; left:0; right:0; z-index:1;
    display:flex; gap:1.6rem; justify-content:center; padding:1.4rem 1rem;
    font-size:.72rem; color:var(--sub);
  }
  footer a{color:var(--sub); text-decoration:none}
  footer a:hover{color:var(--ink)}
  @media (max-height:700px){
    .terminal-body{height:118px}
  }
  @media (max-height:560px){
    .wordmark{font-size:1.8rem;margin-bottom:.5rem}
    .tagline{margin-bottom:1rem}
    .terminal{display:none}
    footer{padding:.8rem 1rem}
  }
</style>
</head>
<body>
  <div class="grid" aria-hidden="true"></div>
  <canvas class="graphic" id="constellation" aria-hidden="true"></canvas>

  <div class="waves" aria-hidden="true">
    <svg class="wave wave-back" viewBox="0 0 2400 200" preserveAspectRatio="none">
      <path d="M0,80 C150,150 350,10 600,80 C850,150 1050,10 1200,80 C1350,150 1550,10 1800,80 C2050,150 2250,10 2400,80 L2400,200 L0,200 Z"/>
    </svg>
    <svg class="wave wave-front" viewBox="0 0 2400 200" preserveAspectRatio="none">
      <path d="M0,110 C200,40 400,180 600,110 C800,40 1000,180 1200,110 C1400,40 1600,180 1800,110 C2000,40 2200,180 2400,110 L2400,200 L0,200 Z"/>
    </svg>
  </div>

  <main>
    <h1 class="wordmark">
      <svg class="sail-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 20 L12 6 L18 20 Z" fill="var(--ink)" opacity=".12"/>
        <path d="M4 20 L12 3 L12 20 Z" fill="#0ea5e9"/>
        <line x1="2.5" y1="20.5" x2="19.5" y2="20.5" stroke="var(--ink)" stroke-width="1.4" stroke-linecap="round"/>
      </svg>
      VELA
    </h1>
    <p class="tagline">
      Self-hosted MLOps.<br>
      <b class="headline">Your models. Your infrastructure. Your data.</b>
    </p>
    <div class="cta-row">
      <a class="btn-primary" href="/login">Get Started</a>
      <a class="link-secondary" href="/docs">Documentation</a>
    </div>

    <div class="terminal" role="img" aria-label="Terminal demo: deploying a model, then detecting and explaining drift">
      <div class="terminal-bar">
        <span class="term-dot r"></span><span class="term-dot y"></span><span class="term-dot g"></span>
        <span class="terminal-title">vela — zsh</span>
      </div>
      <div class="terminal-body">
        <div id="term-log"></div><span class="term-cursor" aria-hidden="true"></span>
      </div>
    </div>
  </main>

  <footer>
    <a href="/docs">Documentation</a>
    <a href="https://github.com/HassanFasseh/vela" target="_blank" rel="noopener">GitHub</a>
    <a href="/about">About</a>
    <a href="/privacy">Privacy</a>
  </footer>

<script>
(function(){
  // Constellation — ~40 nodes drifting in random directions, bouncing off
  // the viewport edges, with connections drawn dynamically between any
  // two nodes within ~150px of each other each frame. Dark navy/slate,
  // low opacity via the .graphic CSS class — an alive, sailing network
  // rather than a static star chart.
  var canvas = document.getElementById('constellation');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');

  var NODE_COUNT = 40;
  var MAX_DIST = 150;
  var SPEED = 0.3;
  var NODE_COLOR = '30, 41, 59'; // dark navy/slate (#1e293b), rgb triplet for rgba()

  var DPR = window.devicePixelRatio || 1;
  var W = 0, H = 0;
  var nodes = [];

  function rand(min, max){ return min + Math.random() * (max - min); }

  function resize(){
    W = canvas.offsetWidth;
    H = canvas.offsetHeight;
    canvas.width = Math.max(1, Math.round(W * DPR));
    canvas.height = Math.max(1, Math.round(H * DPR));
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function seed(){
    nodes = [];
    for (var i = 0; i < NODE_COUNT; i++) {
      var angle = rand(0, Math.PI * 2);
      nodes.push({
        x: rand(0, W),
        y: rand(0, H),
        vx: Math.cos(angle) * SPEED,
        vy: Math.sin(angle) * SPEED,
        r: rand(1.4, 3)
      });
    }
  }

  function step(){
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      n.x += n.vx;
      n.y += n.vy;
      if (n.x <= 0 || n.x >= W) { n.vx *= -1; n.x = Math.min(W, Math.max(0, n.x)); }
      if (n.y <= 0 || n.y >= H) { n.vy *= -1; n.y = Math.min(H, Math.max(0, n.y)); }
    }
  }

  function draw(){
    ctx.clearRect(0, 0, W, H);
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var a = nodes[i], b = nodes[j];
        var dx = a.x - b.x, dy = a.y - b.y;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < MAX_DIST) {
          ctx.strokeStyle = 'rgba(' + NODE_COLOR + ',' + ((1 - dist / MAX_DIST) * 0.5) + ')';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }
    ctx.fillStyle = 'rgba(' + NODE_COLOR + ', 0.85)';
    for (var k = 0; k < nodes.length; k++) {
      var node = nodes[k];
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  var reduceMotion = false;
  try { reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  function loop(){
    step();
    draw();
    requestAnimationFrame(loop);
  }

  resize();
  seed();
  draw();
  if (!reduceMotion) { requestAnimationFrame(loop); }

  var resizeTimer;
  window.addEventListener('resize', function(){
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function(){
      resize();
      seed();
      draw();
    }, 150);
  });
})();
</script>
<script>
(function(){
  var LOG = document.getElementById('term-log');
  if (!LOG) return;
  var LINES = [
    {cls:'cmd', text:'$ vela deploy sentiment-model'},
    {cls:'ok',  text:'\\u2713 Building multi-arch image...'},
    {cls:'ok',  text:'\\u2713 Pushing to registry...'},
    {cls:'ok',  text:'\\u2713 Model live in 47s'},
    {cls:'cmd', text:'$ drift detected \\u2014 score 0.94'},
    {cls:'cmd', text:'$ generating explanation...'},
    {cls:'ok',  text:'\\u2713 confidence score and label distribution shifted'}
  ];
  var LONG_PAUSE_AFTER = 3; // pause after "Model live in 47s" before the drift sequence

  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }

  function renderStatic(){
    LOG.innerHTML = LINES.map(function(l){
      return '<p class="term-line ' + l.cls + '">' + l.text + '</p>';
    }).join('');
  }

  function typeLine(text, cls){
    return new Promise(function(resolve){
      var el = document.createElement('p');
      el.className = 'term-line ' + cls;
      LOG.appendChild(el);
      var i = 0;
      (function step(){
        if (i >= text.length) { resolve(); return; }
        el.textContent += text[i];
        i++;
        setTimeout(step, 16 + Math.random() * 22);
      })();
    });
  }

  async function run(){
    while (true) {
      LOG.innerHTML = '';
      for (var i = 0; i < LINES.length; i++) {
        await typeLine(LINES[i].text, LINES[i].cls);
        await sleep(i === LONG_PAUSE_AFTER ? 1100 : 280);
      }
      await sleep(2200);
    }
  }

  var reduceMotion = false;
  try { reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  if (reduceMotion) { renderStatic(); } else { run(); }
})();
</script>
</body>
</html>"""

@app.post("/deploy")
def deploy(model: Model):
    deploy_model(model)
    return {"status": "deployed", "model": model.name}

@app.get("/timeline")
def timeline(window_minutes: int = 360, job: str = "model-service", pod: str = None):
    return build_timeline(window_minutes, job, pod)

@app.get("/summary")
def summary(window_minutes: int = 360, job: str = "model-service", pod: str = None):
    events = build_timeline(window_minutes, job, pod)
    return {"summary": generate_summary(events)}

@app.get("/models/status")
def models_status():
    statuses = []
    # `job` is the Prometheus job label each service would be scraped
    # under if it had a ServiceMonitor — only model-service actually does
    # (k8s/model-service-monitor.yaml selects app=model-service only), so
    # `instrumented` tells callers up front which of these two has any
    # real metrics/drift behind it, instead of letting them find out by
    # getting an empty query back.
    for model_id, url, name, task, job, instrumented in [
        (1, MODEL_SERVICE_URL, "DistilBERT Sentiment", "sentiment-analysis", "model-service", True),
        (2, MODEL_SERVICE_2_URL, "distilbart-mnli Zero-Shot", "zero-shot-classification", "model-service-2", False),
    ]:
        try:
            r = http_requests.get(f"{url}/health", timeout=3)
            health = r.json()
            statuses.append({
                "id": model_id, "name": name, "task": task, "job": job, "instrumented": instrumented,
                "status": "online", "model": health.get("model", "unknown")
            })
        except Exception:
            statuses.append({
                "id": model_id, "name": name, "task": task, "job": job, "instrumented": instrumented,
                "status": "offline", "model": "unavailable"
            })
    return statuses

@app.post("/predict-proxy")
def predict_proxy(req: PredictRequest):
    if req.model_id == 1:
        url = MODEL_SERVICE_URL
    elif req.model_id == 2:
        url = MODEL_SERVICE_2_URL
    elif req.service_name:
        url = f"http://{req.service_name}.default.svc.cluster.local"
    else:
        raise HTTPException(status_code=400, detail="No model specified")
    try:
        payload = {"text": req.text}
        if req.model_id == 2:
            payload["labels"] = req.labels
        r = http_requests.post(f"{url}/predict", json=payload, timeout=30)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

@app.post("/deploy-model")
def deploy_model_endpoint(req: DeployModelRequest):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        raise HTTPException(status_code=500, detail="GitHub credentials not configured")

    # Save deployment record to DB before triggering
    from backend.app.database import SessionLocal
    from backend.app.db.models import Deployment as DeploymentModel
    db = SessionLocal()
    try:
        record = DeploymentModel(
            name=req.deployment_name,
            model_name=req.model_name,
            task_type=req.task_type,
            source="huggingface",
            status="pending"
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        deployment_id = record.id
    except Exception as e:
        db.rollback()
        deployment_id = None
    finally:
        db.close()

    # Trigger GitHub Actions
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/model-deploy.yml/dispatches"
    resp = http_requests.post(
        url,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        },
        json={
            "ref": "main",
            "inputs": {
                "model_name": req.model_name,
                "task_type": req.task_type,
                "deployment_name": req.deployment_name
            }
        }
    )
    if resp.status_code == 204:
        return {
            "status": "triggered",
            "deployment_name": req.deployment_name,
            "deployment_id": deployment_id
        }
    raise HTTPException(status_code=resp.status_code, detail=resp.text)

@app.get("/deployments")
def deployments():
    try:
        from kubernetes import client as k8s_client, config as k8s_config
        k8s_config.load_incluster_config()
        apps_v1 = k8s_client.AppsV1Api()
        deps = apps_v1.list_namespaced_deployment(
            namespace="default",
            label_selector="managed-by=platform"
        )
        results = []
        for d in deps.items:
            name = d.metadata.name
            ready = d.status.ready_replicas or 0
            desired = d.spec.replicas or 1
            status = "running" if ready == desired else "starting"
            model_name = next(
                (e.value for c in d.spec.template.spec.containers
                 for e in (c.env or []) if e.name == "MODEL_NAME"),
                "unknown"
            )
            task_type = next(
                (e.value for c in d.spec.template.spec.containers
                 for e in (c.env or []) if e.name == "TASK_TYPE"),
                "unknown"
            )
            results.append({
                "name": name,
                "model_name": model_name,
                "task_type": task_type,
                "status": status,
                "ready": ready,
                "desired": desired
            })
        return results
    except Exception as e:
        return []



@app.post("/api/v1/predict")
def api_predict(req: PredictRequest, x_api_key: str = fastapi.Header(None, alias="X-API-Key"), authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import verify_api_key

    # Accept key from X-API-Key header or Authorization: Bearer aodp_...
    raw_key = x_api_key
    if not raw_key and authorization and authorization.startswith("Bearer aodp_"):
        raw_key = authorization.split(" ")[1]

    if not raw_key:
        raise HTTPException(status_code=401, detail="API key required. Pass X-API-Key header or Authorization: Bearer <key>")

    if not raw_key.startswith("aodp_"):
        raise HTTPException(status_code=401, detail="Invalid API key format. Keys must start with aodp_")

    # deployment_id is the only routing key this endpoint accepts now —
    # every prediction goes through a real Deployment row so its
    # input_type/model_type can actually be looked up (see below). The
    # old model_id==1/2/service_name fallback (still used by the
    # separate /predict-proxy, unaffected) is gone here: the two
    # hardcoded core services were never Deployment rows to begin with,
    # so they were never reachable through a real permission check
    # anyway (see the comment that used to be here about that).
    if not req.deployment_id:
        raise HTTPException(status_code=400, detail="deployment_id is required")

    db = SessionLocal()
    try:
        api_key = verify_api_key(db, raw_key)
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")

        if api_key.team_id or api_key.deployment_id:
            from backend.app.services.teams import check_team_model_permission
            if not check_team_model_permission(db, api_key, req.deployment_id):
                raise HTTPException(status_code=403, detail="Your API key does not have permission to use this model")

        from backend.app.db.models import Deployment
        deployment = db.query(Deployment).filter(Deployment.id == req.deployment_id).first()
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        if not deployment.is_active:
            raise HTTPException(status_code=403, detail="This model has been disabled")

        # Which field is required depends on what this specific
        # deployment actually expects — not a global assumption of
        # "text", which is what broke json/file-typed custom models
        # before this endpoint knew to look the deployment up first.
        input_type = deployment.input_type or "text"
        if input_type == "text":
            if not req.text:
                raise HTTPException(status_code=400, detail="This model expects input_type=text — pass the 'text' field")
        elif input_type == "json":
            if req.data is None:
                raise HTTPException(status_code=400, detail="This model expects input_type=json — pass the 'data' field")
        elif input_type == "file":
            if not req.file:
                raise HTTPException(status_code=400, detail="This model expects input_type=file — pass the 'file' field (base64-encoded)")
        else:
            raise HTTPException(status_code=500, detail=f"Deployment has an unrecognized input_type: {input_type!r}")

        url = f"http://{deployment.name}.default.svc.cluster.local"

        try:
            if deployment.model_type == "custom":
                # custom-runner (custom-runner/base/main.py) shapes its
                # own /predict request by INPUT_TYPE — match it exactly rather
                # than always sending {"text": ...} the way the built-in
                # HuggingFace runners do.
                if input_type == "text":
                    r = http_requests.post(f"{url}/predict", json={"text": req.text}, timeout=30)
                elif input_type == "json":
                    r = http_requests.post(f"{url}/predict", json={"data": req.data}, timeout=30)
                else:  # file
                    try:
                        import base64
                        file_bytes = base64.b64decode(req.file)
                    except Exception:
                        raise HTTPException(status_code=400, detail="'file' must be valid base64")
                    # Longer timeout than the other two branches — file
                    # payloads (images, audio) are typically bigger and
                    # slower to preprocess than a short text/json body.
                    r = http_requests.post(f"{url}/predict", files={"file": ("upload", file_bytes)}, timeout=60)
            else:
                # Built-in HuggingFace runners (model-runner) branch on
                # INPUT_TYPE the same way custom-runner does now — match
                # whichever field this deployment's input_type expects
                # rather than always sending {"text": ...} (that only
                # ever worked for the text-input deployments; image/audio
                # models set up with input_type=file or json need their
                # own field forwarded instead).
                if input_type == "text":
                    payload = {"text": req.text}
                    if deployment.task_type == "zero-shot-classification":
                        payload["labels"] = req.labels
                    r = http_requests.post(f"{url}/predict", json=payload, timeout=30)
                elif input_type == "json":
                    r = http_requests.post(f"{url}/predict", json={"data": req.data}, timeout=30)
                else:  # file
                    # Longer timeout, same reasoning as the custom-runner
                    # file branch above — image/audio payloads are bigger
                    # and slower to preprocess than a short text/json body.
                    r = http_requests.post(f"{url}/predict", json={"file": req.file}, timeout=60)

            result = r.json()

            # Fire-and-forget drift telemetry — see services/drift_tracker.py.
            # Every deployment routed through this one endpoint (both
            # model-runner and custom-runner) gets a window in Redis this
            # way, not just model-service's own hardcoded pipeline.
            from backend.app.services import drift_tracker
            drift_tracker.record_prediction(req.deployment_id, result, len(req.text) if req.text else 0)

            return {
                "workspace_id": api_key.workspace_id,
                "deployment_id": req.deployment_id,
                "result": result
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Model service error: {str(e)}")
    finally:
        db.close()


from fastapi import UploadFile, File, Form

@app.post("/api/v1/upload-model")
async def upload_model(
    file: UploadFile = File(...),
    model_name: str = Form(...),
    workspace_id: int = Form(...),
    x_api_key: str = fastapi.Header(None, alias="X-API-Key")
):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import verify_api_key
    from backend.app.services.storage import upload_model as store_model
    from backend.app.db.models import Deployment as DeploymentModel
    from datetime import datetime

    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    db = SessionLocal()
    try:
        api_key = verify_api_key(db, x_api_key)
        if not api_key or api_key.workspace_id != workspace_id:
            raise HTTPException(status_code=401, detail="Invalid API key for this workspace")

        file_bytes = await file.read()
        if len(file_bytes) > 500 * 1024 * 1024:  # 500MB limit
            raise HTTPException(status_code=413, detail="File too large. Maximum size is 500MB")

        storage_path = store_model(file_bytes, workspace_id, model_name)

        record = DeploymentModel(
            name=model_name,
            model_name=model_name,
            task_type="custom",
            source="upload",
            storage_path=storage_path,
            status="uploaded",
            workspace_id=workspace_id,
            created_at=datetime.utcnow()
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Model uploaded successfully",
            "deployment_id": record.id,
            "storage_path": storage_path,
            "size_mb": round(len(file_bytes) / 1024 / 1024, 2)
        }
    finally:
        db.close()

@app.get("/api/v1/workspace/{workspace_id}/models")
def list_workspace_models(
    workspace_id: int,
    x_api_key: str = fastapi.Header(None, alias="X-API-Key")
):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import verify_api_key
    from backend.app.services.storage import list_workspace_models as list_models

    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    db = SessionLocal()
    try:
        api_key = verify_api_key(db, x_api_key)
        if not api_key or api_key.workspace_id != workspace_id:
            raise HTTPException(status_code=401, detail="Invalid API key for this workspace")
        return list_models(workspace_id)
    finally:
        db.close()


# =========================================================================
# Custom models — user-supplied predict.py + weights, served by one
# fixed image (custom-runner/base/, ghcr.io/hassanfasseh/vela/
# custom-runner:base) shared across every custom deployment instead of a
# per-deployment build. predict.py/model_files are mounted at runtime
# (ConfigMap + PVC) rather than baked in — see
# backend/app/services/k8s_custom.py for the actual Kubernetes
# operations, and custom-runner/predict_template.py for the
# load_model()/predict() interface contract.
# =========================================================================

# Not GITHUB_TOKEN-gated like the endpoints below — this is a static
# template file, no more sensitive than the docs. No auth required, same
# posture as GET /model-cards/{id} (see admin_pages.py's comment on it).
@app.get("/api/v1/custom-model-template")
def custom_model_template():
    # Resolves the same way in both local dev (cwd = repo root) and the
    # deployed image (Dockerfile.backend copies custom-runner/predict_
    # template.py to the same path, relative to WORKDIR, as backend/) —
    # two directories up from this file is the repo root / image WORKDIR
    # either way.
    template_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "custom-runner", "predict_template.py")
    )
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="Template not found")
    return FileResponse(
        template_path,
        media_type="text/x-python",
        filename="predict_template.py"
    )

def _resolve_custom_model_actor(db, authorization: str, x_api_key: str):
    """Auth for the three custom-model endpoints below: either a workspace
    X-API-Key (existing behavior) or an admin's JWT (Authorization:
    Bearer), which bypasses the API key requirement entirely. Returns
    (api_key_or_None, is_admin_jwt). Raises 401 if neither checks out."""
    from backend.app.services.auth import verify_api_key, decode_token
    from backend.app.db.models import User

    if authorization and authorization.startswith("Bearer "):
        payload = decode_token(authorization.split(" ", 1)[1])
        if payload:
            user = db.query(User).filter(User.id == int(payload["sub"])).first()
            if user and user.is_admin and user.is_active:
                return None, True
    if x_api_key:
        api_key = verify_api_key(db, x_api_key)
        if api_key:
            return api_key, False
    raise HTTPException(status_code=401, detail="API key or admin session required")

@app.post("/api/v1/upload-custom-model")
async def upload_custom_model(
    predict_file: UploadFile = File(...),
    model_files: list[UploadFile] = File(...),
    deployment_name: str = Form(...),
    input_type: str = Form(...),
    workspace_id: int = Form(...),
    input_schema: str = Form(None),
    task_type: str = Form(None),
    requirements_file: UploadFile = File(None),
    pvc_size_gb: int = Form(1),
    x_api_key: str = fastapi.Header(None, alias="X-API-Key"),
    authorization: str = fastapi.Header(None)
):
    from backend.app.database import SessionLocal
    from backend.app.services.storage import get_client, ensure_bucket, BUCKET_NAME
    from backend.app.services import k8s_custom
    from backend.app.db.models import Deployment as DeploymentModel
    from datetime import datetime
    import io
    import re

    if input_type not in ("text", "json", "file"):
        raise HTTPException(status_code=400, detail="input_type must be one of: text, json, file")
    if not predict_file.filename or not predict_file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="predict_file must be a .py file")
    if not model_files:
        raise HTTPException(status_code=400, detail="At least one model file is required")
    # deployment_name becomes a Kubernetes resource name (Deployment,
    # Service, ConfigMap, Job, PVC — see k8s_custom.py) in several
    # places now, not just a display label, so it has to be a valid
    # DNS-1123 label — the admin form already enforces this client-side,
    # this is the server-side backstop.
    if not re.match(r"^[a-z0-9-]+$", deployment_name):
        raise HTTPException(status_code=400, detail="deployment_name must be lowercase letters, numbers, and hyphens only")

    db = SessionLocal()
    try:
        api_key, is_admin_jwt = _resolve_custom_model_actor(db, authorization, x_api_key)
        if not is_admin_jwt:
            if api_key.workspace_id != workspace_id:
                raise HTTPException(status_code=401, detail="Invalid API key for this workspace")
            # "admin key": an unscoped workspace key, not one issued to a team
            # for calling one specific model. Publishing a new custom model
            # is a workspace-admin action — same trust level /api/v1/upload-
            # model already assumes implicitly by only checking workspace_id.
            if api_key.team_id or api_key.deployment_id:
                raise HTTPException(status_code=403, detail="This endpoint requires an unscoped workspace API key")

        object_prefix = f"workspace-{workspace_id}/custom/{deployment_name}"
        minio_path = f"{BUCKET_NAME}/{object_prefix}"

        ensure_bucket()
        client = get_client()

        predict_bytes = await predict_file.read()
        client.put_object(
            BUCKET_NAME,
            f"{object_prefix}/predict.py",
            io.BytesIO(predict_bytes),
            length=len(predict_bytes),
            content_type="text/x-python"
        )

        for f in model_files:
            file_bytes = await f.read()
            client.put_object(
                BUCKET_NAME,
                f"{object_prefix}/model_files/{f.filename}",
                io.BytesIO(file_bytes),
                length=len(file_bytes),
                content_type="application/octet-stream"
            )

        # Stored, but not actually used by anything in the cloud-native
        # flow below — custom-runner:base is one fixed image (fastapi,
        # uvicorn, scikit-learn, joblib, pandas, numpy only) shared by
        # every custom deployment, with no per-deployment build step left
        # to install this into. Kept so nothing breaks for callers still
        # sending it; see the PR/commit this shipped in for the tradeoff.
        if requirements_file is not None and requirements_file.filename:
            requirements_bytes = await requirements_file.read()
            client.put_object(
                BUCKET_NAME,
                f"{object_prefix}/requirements.txt",
                io.BytesIO(requirements_bytes),
                length=len(requirements_bytes),
                content_type="text/plain"
            )

        record = DeploymentModel(
            workspace_id=workspace_id,
            name=deployment_name,
            model_name=deployment_name,
            # Free-text label for what the model actually does (e.g.
            # "fraud-detection") — admin-supplied, optional, purely
            # descriptive. Falls back to "custom" (the old fixed value,
            # before this field existed) rather than an empty string so
            # every listing that renders task_type still has something
            # to show.
            task_type=task_type.strip() if task_type and task_type.strip() else "custom",
            source="upload",
            model_type="custom",
            input_type=input_type,
            minio_path=minio_path,
            input_schema=input_schema,
            pvc_name=k8s_custom.pvc_name_for(deployment_name),
            status="provisioning",
            created_at=datetime.utcnow()
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        deployment_id = record.id

        # ConfigMap + PVC + download Job only — the Deployment/Service
        # themselves are created lazily by GET /api/v1/custom-model-
        # status/{id} the first time it's polled after the Job succeeds
        # (see k8s_custom.get_status()'s docstring for why: creating them
        # here would mean blocking this request on however long the
        # model-weights download takes).
        try:
            predict_text = predict_bytes.decode("utf-8")
            cm_name = k8s_custom.create_predict_configmap(deployment_name, predict_text)
            pvc = k8s_custom.create_model_pvc(deployment_name, pvc_size_gb)
            k8s_custom.create_download_job(deployment_name, minio_path, pvc)
        except Exception as e:
            record.status = "failed"
            db.commit()
            raise HTTPException(status_code=500, detail=f"Kubernetes provisioning failed: {e}")
    finally:
        db.close()

    return {
        "deployment_id": deployment_id,
        "minio_path": minio_path,
        "status": "provisioning"
    }

@app.post("/api/v1/deploy-custom/{deployment_id}")
def redeploy_custom_model(deployment_id: int, x_api_key: str = fastapi.Header(None, alias="X-API-Key")):
    """Redeploy without re-uploading: re-runs the download Job (in case
    MinIO's contents changed since the last deploy) and rolling-restarts
    the running pod so it re-mounts model_files/ fresh — a ConfigMap
    volume's file content updates on its own after a short kubelet
    propagation delay, but the already-running Python process never
    re-imports predict.py without a restart either way."""
    from backend.app.database import SessionLocal
    from backend.app.services.auth import verify_api_key
    from backend.app.services import k8s_custom
    from backend.app.db.models import Deployment as DeploymentModel
    from kubernetes.client.rest import ApiException

    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    db = SessionLocal()
    try:
        api_key = verify_api_key(db, x_api_key)
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

        deployment = db.query(DeploymentModel).filter(DeploymentModel.id == deployment_id).first()
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        if deployment.workspace_id != api_key.workspace_id:
            raise HTTPException(status_code=401, detail="Invalid API key for this workspace")
        if api_key.team_id or api_key.deployment_id:
            raise HTTPException(status_code=403, detail="This endpoint requires an unscoped workspace API key")
        if deployment.model_type != "custom" or not deployment.minio_path:
            raise HTTPException(status_code=400, detail="This deployment has no custom-model files in MinIO to redeploy")

        deployment.status = "provisioning"
        db.commit()
        deployment_name = deployment.name
        minio_path = deployment.minio_path
        pvc = deployment.pvc_name or k8s_custom.pvc_name_for(deployment_name)
    finally:
        db.close()

    try:
        k8s_custom.create_download_job(deployment_name, minio_path, pvc)
        try:
            k8s_custom.restart_deployment(deployment_name)
        except ApiException as e:
            # No Deployment yet (the original upload's Job never
            # succeeded, so it was never lazily created) — the status
            # endpoint will create it once this new Job run succeeds,
            # same as a first-time upload.
            if e.status != 404:
                raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redeploy failed: {e}")

    return {
        "deployment_id": deployment_id,
        "minio_path": minio_path,
        "status": "provisioning"
    }

def _user_can_view_deployment(db, user_id: int, deployment_id: int) -> bool:
    """A plain team member whose team has been granted view or predict
    access to this exact deployment — the same grant the Model Health/
    Drift pages use to decide which models show up in a member's model
    picker in the first place, so this just makes that view actually
    fetchable instead of admin/API-key-only."""
    from backend.app.db.models import TeamMember, TeamModelPermission
    return db.query(TeamModelPermission).join(
        TeamMember, TeamMember.team_id == TeamModelPermission.team_id
    ).filter(
        TeamMember.user_id == user_id,
        TeamModelPermission.deployment_id == deployment_id,
        (TeamModelPermission.can_view_metrics == True) | (TeamModelPermission.can_predict == True),
    ).first() is not None

@app.get("/api/v1/custom-model-status/{deployment_id}")
def custom_model_status(deployment_id: int, x_api_key: str = fastapi.Header(None, alias="X-API-Key"), authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services import k8s_custom
    from backend.app.db.models import Deployment as DeploymentModel

    db = SessionLocal()
    try:
        try:
            api_key, is_admin_jwt = _resolve_custom_model_actor(db, authorization, x_api_key)
            authorized = True
        except HTTPException:
            api_key, is_admin_jwt, authorized = None, False, False

        deployment = db.query(DeploymentModel).filter(DeploymentModel.id == deployment_id).first()
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")

        if not authorized:
            from backend.app.services.auth import decode_token
            user_id = None
            if authorization and authorization.startswith("Bearer "):
                payload = decode_token(authorization.split(" ", 1)[1])
                if payload:
                    user_id = int(payload["sub"])
            if not user_id or not _user_can_view_deployment(db, user_id, deployment_id):
                raise HTTPException(status_code=401, detail="API key, admin session, or team access to this model required")
        elif not is_admin_jwt and deployment.workspace_id != api_key.workspace_id:
            raise HTTPException(status_code=401, detail="Invalid API key for this workspace")
        if deployment.model_type != "custom":
            raise HTTPException(status_code=400, detail="Not a custom model deployment")

        pvc = deployment.pvc_name or k8s_custom.pvc_name_for(deployment.name)
        cm_name = k8s_custom.configmap_name(deployment.name)

        try:
            result = k8s_custom.get_status(deployment.name, cm_name, pvc, deployment.input_type, deployment.input_schema)
        except Exception as e:
            return {"deployment_id": deployment_id, "phase": "unknown", "detail": str(e)}

        # Keep the DB row in sync — /admin/deployments' table reads
        # Deployment.status directly, not this endpoint, so without this
        # it would stay stuck on whatever upload/redeploy last set
        # ("provisioning") even once the model is actually running.
        new_status = {"running": "running", "failed": "failed"}.get(result["phase"], "provisioning")
        if deployment.status != new_status:
            deployment.status = new_status
            db.commit()

        return {"deployment_id": deployment_id, **result}
    finally:
        db.close()

@app.delete("/api/v1/custom-model/{deployment_id}")
def delete_custom_model(deployment_id: int, x_api_key: str = fastapi.Header(None, alias="X-API-Key"), authorization: str = fastapi.Header(None)):
    """No equivalent existed for any deployment type before this — added
    specifically so a custom deployment's Kubernetes resources (and
    MinIO files are NOT deleted here; they're the durable copy) have
    somewhere to actually get torn down instead of leaking forever."""
    from backend.app.database import SessionLocal
    from backend.app.services import k8s_custom
    from backend.app.db.models import Deployment as DeploymentModel, TeamModelPermission

    db = SessionLocal()
    try:
        api_key, is_admin_jwt = _resolve_custom_model_actor(db, authorization, x_api_key)

        deployment = db.query(DeploymentModel).filter(DeploymentModel.id == deployment_id).first()
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        if not is_admin_jwt:
            if deployment.workspace_id != api_key.workspace_id:
                raise HTTPException(status_code=401, detail="Invalid API key for this workspace")
            if api_key.team_id or api_key.deployment_id:
                raise HTTPException(status_code=403, detail="This endpoint requires an unscoped workspace API key")

        if deployment.model_type == "custom":
            try:
                k8s_custom.delete_all(deployment.name, deployment.pvc_name)
            except Exception as e:
                # A k8s hiccup here shouldn't block removing the DB row
                # below — log it and proceed rather than leaving the
                # admin stuck with a deployment they can't remove from
                # the UI at all.
                print(f"[custom-model-delete] k8s cleanup failed for {deployment.name}: {e}", flush=True)

        # deployments.id is a real FK target for TeamModelPermission —
        # Postgres would reject deleting the row out from under it
        # otherwise.
        db.query(TeamModelPermission).filter(TeamModelPermission.deployment_id == deployment_id).delete()
        db.delete(deployment)
        db.commit()
        return {"message": "Deployment deleted"}
    finally:
        db.close()

# HuggingFace deployments (model-deploy.yml) predate workspace-scoping —
# deploy_model_endpoint() below never sets workspace_id, so it's always
# NULL on these rows. The ownership check every other /api/v1/*
# endpoint here does (deployment.workspace_id != api_key.workspace_id)
# would reject every unscoped key on every one of them if applied
# unconditionally; skipped specifically when workspace_id IS NULL
# instead of requiring a match that can never exist. Shared by both
# endpoints below.
def _check_deployment_key_ownership(deployment, api_key):
    if deployment.workspace_id is not None and deployment.workspace_id != api_key.workspace_id:
        raise HTTPException(status_code=401, detail="Invalid API key for this workspace")
    if api_key.team_id or api_key.deployment_id:
        raise HTTPException(status_code=403, detail="This endpoint requires an unscoped workspace API key")

class DeploymentUpdate(BaseModel):
    is_active: bool

@app.patch("/api/v1/deployment/{deployment_id}")
def update_deployment(deployment_id: int, req: DeploymentUpdate, x_api_key: str = fastapi.Header(None, alias="X-API-Key")):
    """"Disable"/"Enable" on /admin/models — reversible, doesn't touch
    anything running. See Deployment.is_active's own comment for what
    disabling actually does (blocks /api/v1/predict, hides from member
    dashboards)."""
    from backend.app.database import SessionLocal
    from backend.app.services.auth import verify_api_key
    from backend.app.db.models import Deployment as DeploymentModel

    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    db = SessionLocal()
    try:
        api_key = verify_api_key(db, x_api_key)
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

        deployment = db.query(DeploymentModel).filter(DeploymentModel.id == deployment_id).first()
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        _check_deployment_key_ownership(deployment, api_key)

        deployment.is_active = req.is_active
        db.commit()
        return {"deployment_id": deployment_id, "is_active": deployment.is_active}
    finally:
        db.close()

@app.delete("/api/v1/deployment/{deployment_id}")
def delete_deployment(deployment_id: int, x_api_key: str = fastapi.Header(None, alias="X-API-Key")):
    """Delete for HuggingFace deployments — model-deploy.yml's inline
    manifest is just a Deployment + Service, no ConfigMap/PVC/Job, so
    this is deliberately separate from DELETE /api/v1/custom-model/{id}
    rather than one endpoint branching on model_type: calling this on a
    custom deployment would tear down its Deployment+Service but leave
    the ConfigMap/PVC/Job behind as orphans, so it's rejected instead."""
    from backend.app.database import SessionLocal
    from backend.app.services.auth import verify_api_key
    from backend.app.services import k8s_custom
    from backend.app.db.models import Deployment as DeploymentModel, TeamModelPermission

    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    db = SessionLocal()
    try:
        api_key = verify_api_key(db, x_api_key)
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

        deployment = db.query(DeploymentModel).filter(DeploymentModel.id == deployment_id).first()
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")
        if deployment.model_type == "custom":
            raise HTTPException(status_code=400, detail="This is a custom model deployment — use DELETE /api/v1/custom-model/{id} instead")
        _check_deployment_key_ownership(deployment, api_key)

        try:
            k8s_custom.delete_deployment_and_service(deployment.name)
        except Exception as e:
            # Same reasoning as delete_custom_model — don't let a k8s
            # hiccup block removing the DB row.
            print(f"[deployment-delete] k8s cleanup failed for {deployment.name}: {e}", flush=True)

        db.query(TeamModelPermission).filter(TeamModelPermission.deployment_id == deployment_id).delete()
        db.delete(deployment)
        db.commit()
        return {"message": "Deployment deleted"}
    finally:
        db.close()

class TaskTypeUpdate(BaseModel):
    task_type: str

@app.patch("/api/v1/deployment/{deployment_id}/task-type")
def update_deployment_task_type(deployment_id: int, req: TaskTypeUpdate, authorization: str = fastapi.Header(None)):
    """Inline edit target for /admin/models' task_type cell. JWT + admin
    auth (like GET /admin/deployment-registry) rather than X-API-Key like
    this deployment's sibling endpoints above — this is reached directly
    from the admin's own session with no per-workspace key involved."""
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.db.models import User, Deployment as DeploymentModel

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")

        deployment = db.query(DeploymentModel).filter(DeploymentModel.id == deployment_id).first()
        if not deployment:
            raise HTTPException(status_code=404, detail="Deployment not found")

        task_type = req.task_type.strip()
        if not task_type:
            raise HTTPException(status_code=400, detail="task_type cannot be empty")
        deployment.task_type = task_type
        db.commit()
        return {"deployment_id": deployment_id, "task_type": deployment.task_type}
    finally:
        db.close()


from backend.app.db.models import RemediationConfig, RemediationLog

class RemediationConfigCreate(BaseModel):
    deployment_id: int
    drift_threshold: float = 0.5
    action_type: str = "github_issue"
    target: str = ""

@app.post("/api/v1/remediations")
def create_remediation(req: RemediationConfigCreate, x_api_key: str = fastapi.Header(None, alias="X-API-Key")):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import verify_api_key
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
    db = SessionLocal()
    try:
        api_key = verify_api_key(db, x_api_key)
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        config = RemediationConfig(
            deployment_id=req.deployment_id,
            workspace_id=api_key.workspace_id,
            drift_threshold=req.drift_threshold,
            action_type=req.action_type,
            target=req.target
        )
        db.add(config)
        db.commit()
        db.refresh(config)
        return {"id": config.id, "message": f"Remediation configured: {req.action_type} when drift > {req.drift_threshold}"}
    finally:
        db.close()

@app.get("/api/v1/remediations/{workspace_id}")
def list_remediations(workspace_id: int, x_api_key: str = fastapi.Header(None, alias="X-API-Key")):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import verify_api_key
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
    db = SessionLocal()
    try:
        api_key = verify_api_key(db, x_api_key)
        if not api_key or api_key.workspace_id != workspace_id:
            raise HTTPException(status_code=401, detail="Invalid API key")
        configs = db.query(RemediationConfig).filter(RemediationConfig.workspace_id == workspace_id).all()
        return [{"id": c.id, "deployment_id": c.deployment_id, "drift_threshold": c.drift_threshold, "action_type": c.action_type, "target": c.target, "is_active": c.is_active, "last_triggered_at": c.last_triggered_at} for c in configs]
    finally:
        db.close()

@app.get("/api/v1/remediation-logs/{workspace_id}")
def remediation_logs(workspace_id: int, x_api_key: str = fastapi.Header(None, alias="X-API-Key")):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import verify_api_key
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
    db = SessionLocal()
    try:
        api_key = verify_api_key(db, x_api_key)
        if not api_key or api_key.workspace_id != workspace_id:
            raise HTTPException(status_code=401, detail="Invalid API key")
        logs = db.query(RemediationLog).filter(RemediationLog.deployment_id.in_(
            [c.deployment_id for c in db.query(RemediationConfig).filter(RemediationConfig.workspace_id == workspace_id).all()]
        )).order_by(RemediationLog.triggered_at.desc()).limit(50).all()
        return [{"id": l.id, "deployment_id": l.deployment_id, "drift_score": l.drift_score, "action_type": l.action_type, "status": l.status, "triggered_at": l.triggered_at} for l in logs]
    finally:
        db.close()

@app.post("/api/v1/remediations/{config_id}/test")
def test_remediation(config_id: int, x_api_key: str = fastapi.Header(None, alias="X-API-Key")):
    """Manually trigger a remediation to test it."""
    from backend.app.database import SessionLocal
    from backend.app.services.auth import verify_api_key
    from backend.app.services.remediation import fire_github_issue, fire_webhook, fire_retrain
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
    db = SessionLocal()
    try:
        api_key = verify_api_key(db, x_api_key)
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        config = db.query(RemediationConfig).filter(RemediationConfig.id == config_id).first()
        if not config:
            raise HTTPException(status_code=404, detail="Config not found")
        if config.action_type == "github_issue":
            result = fire_github_issue("test-deployment", 0.99, config.target)
        elif config.action_type == "webhook":
            result = fire_webhook("test-deployment", 0.99, config.target)
        else:
            result = fire_retrain("test-deployment", 0.99, config.target)
        return result
    finally:
        db.close()



from backend.app.services.tickets import (
    create_ticket, get_all_tickets, get_user_tickets,
    get_team_tickets, update_ticket_status
)

class TicketCreate(BaseModel):
    title: str
    description: str
    ticket_type: str = "bug"
    severity: str = "medium"
    deployment_id: int = None
    team_id: int = None
    evidence: str = ""

class TicketUpdate(BaseModel):
    status: str
    resolution_note: str = ""

class UserCreate(BaseModel):
    username: str
    name: str
    password: str
    is_admin: bool = False
    force_password_change: bool = True

class PasswordChange(BaseModel):
    new_password: str

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/auth/login")
def login(req: LoginRequest):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import authenticate_user, create_access_token
    db = SessionLocal()
    try:
        user = authenticate_user(db, req.username, req.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        token = create_access_token(user.id, user.username)
        return {
            "token": token,
            "user": {
                "id": user.id,
                "username": user.username,
                "name": user.name,
                "is_admin": user.is_admin,
                "force_password_change": user.force_password_change
            }
        }
    finally:
        db.close()

@app.get("/auth/me")
def me(authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.db.models import User
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return {
            "id": user.id,
            "username": user.username,
            "name": user.name,
            "is_admin": user.is_admin,
            "force_password_change": user.force_password_change
        }
    finally:
        db.close()

@app.post("/auth/change-password")
def change_password_endpoint(req: PasswordChange, authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token, change_password
    from backend.app.db.models import User
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        success = change_password(db, int(payload["sub"]), req.new_password)
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        return {"message": "Password changed successfully"}
    finally:
        db.close()

# Admin endpoints
@app.post("/admin/users")
def admin_create_user(req: UserCreate, authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token, create_user, get_user_by_username
    from backend.app.db.models import User
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        if get_user_by_username(db, req.username):
            raise HTTPException(status_code=400, detail="Username already exists")
        user = create_user(db, req.username, req.name, req.password,
                          req.is_admin, admin.id, req.force_password_change)
        return {"id": user.id, "username": user.username, "name": user.name,
                "is_admin": user.is_admin, "force_password_change": user.force_password_change}
    finally:
        db.close()

@app.get("/admin/users")
def admin_list_users(authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.db.models import User
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        users = db.query(User).all()
        return [{"id": u.id, "username": u.username, "name": u.name,
                 "is_admin": u.is_admin, "is_active": u.is_active,
                 "force_password_change": u.force_password_change,
                 "created_at": u.created_at} for u in users]
    finally:
        db.close()

@app.patch("/admin/users/{user_id}/deactivate")
def admin_deactivate_user(user_id: int, authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.db.models import User
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        if int(payload["sub"]) == user_id:
            raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_active = False
        db.commit()
        return {"message": f"User {user.username} deactivated"}
    finally:
        db.close()

@app.patch("/admin/users/{user_id}/reactivate")
def admin_reactivate_user(user_id: int, authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.db.models import User
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_active = True
        db.commit()
        return {"message": f"User {user.username} reactivated"}
    finally:
        db.close()

@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, authorization: str = fastapi.Header(None)):
    """Permanently removes the user row (unlike the old behavior, which
    only deactivated it — see PATCH .../deactivate for that now). Rows
    that are squarely this user's own data (team/workspace membership,
    their access requests) are deleted with them; nullable "who did
    this" references on other people's data (deployments, model cards,
    granted permissions, resolved tickets) are cleared instead of
    cascading, so deleting a user never takes someone else's records
    with it. A user who still owns a workspace or has filed_by tickets
    (both non-nullable FKs) can't be hard-deleted at all — Postgres
    rejects it and the admin needs to reassign/resolve those first."""
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.db.models import (
        User, WorkspaceMember, TeamMember, AccessRequest,
        Deployment, ModelCard, TeamModelPermission, Ticket,
    )
    from sqlalchemy.exc import IntegrityError
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        if int(payload["sub"]) == user_id:
            raise HTTPException(status_code=400, detail="Cannot delete yourself")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        username = user.username

        db.query(TeamMember).filter(TeamMember.user_id == user_id).delete()
        db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user_id).delete()
        db.query(AccessRequest).filter(AccessRequest.user_id == user_id).delete()

        db.query(Deployment).filter(Deployment.created_by == user_id).update({"created_by": None})
        db.query(ModelCard).filter(ModelCard.created_by == user_id).update({"created_by": None})
        db.query(TeamModelPermission).filter(TeamModelPermission.granted_by == user_id).update({"granted_by": None})
        db.query(AccessRequest).filter(AccessRequest.reviewed_by == user_id).update({"reviewed_by": None})
        db.query(Ticket).filter(Ticket.resolved_by == user_id).update({"resolved_by": None})

        db.delete(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Cannot delete this user: they still own a workspace or have tickets filed under their name. Reassign or resolve those first."
            )
        return {"message": f"User {username} permanently deleted"}
    finally:
        db.close()

@app.get("/admin/tickets")
def admin_get_tickets(status: str = None, authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.db.models import User
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        return get_all_tickets(db, status)
    finally:
        db.close()

@app.patch("/admin/tickets/{ticket_id}")
def admin_update_ticket(ticket_id: int, req: TicketUpdate, authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.db.models import User
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        ticket = update_ticket_status(db, ticket_id, req.status, admin.id, req.resolution_note)
        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")
        return {"id": ticket.id, "status": ticket.status, "message": "Ticket updated"}
    finally:
        db.close()

# User ticket endpoints
@app.post("/tickets")
def file_ticket(req: TicketCreate, authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.db.models import WorkspaceMember
    db = SessionLocal()
    try:
        user, db = get_verified_user(authorization, db)
        ws = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).first()
        workspace_id = ws.workspace_id if ws else None
        ticket = create_ticket(
            db, req.title, req.description, req.ticket_type,
            req.severity, user.id, req.deployment_id,
            workspace_id, req.team_id, req.evidence
        )
        return {"id": ticket.id, "message": "Ticket filed successfully", "status": ticket.status}
    finally:
        db.close()

@app.get("/tickets/my")
def my_tickets(authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    db = SessionLocal()
    try:
        user, db = get_verified_user(authorization, db)
        return get_user_tickets(db, user.id)
    finally:
        db.close()



@app.post("/admin/teams/{team_id}/users/{user_id}")
def admin_assign_user_to_team(team_id: int, user_id: int, role: str = "member", authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.services.teams import add_team_member
    from backend.app.db.models import User, Team
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        team = db.query(Team).filter(Team.id == team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="Team not found")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        member = add_team_member(db, team_id, user_id, role)
        return {"message": f"{user.username} added to team {team.name} as {role}",
                "team_id": team_id, "user_id": user_id, "role": member.role}
    finally:
        db.close()

@app.delete("/admin/teams/{team_id}/users/{user_id}")
def admin_remove_user_from_team(team_id: int, user_id: int, authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.services.teams import remove_team_member
    from backend.app.db.models import User, Team
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        success = remove_team_member(db, team_id, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Member not found")
        return {"message": f"User {user_id} removed from team {team_id}"}
    finally:
        db.close()

@app.get("/admin/teams")
def admin_list_teams(authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.services.teams import get_workspace_teams, get_team_members, get_team_permissions
    from backend.app.db.models import User, Workspace
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        from backend.app.db.models import Team
        teams = db.query(Team).all()
        return [{
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "workspace_id": t.workspace_id,
            "members": get_team_members(db, t.id),
            "permissions": get_team_permissions(db, t.id)
        } for t in teams]
    finally:
        db.close()

@app.post("/admin/teams")
def admin_create_team(name: str, description: str = "", workspace_id: int = 1, authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.services.teams import create_team
    from backend.app.db.models import User
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        team = create_team(db, workspace_id, name, description, admin.id)
        return {"id": team.id, "name": team.name, "description": team.description}
    finally:
        db.close()

# GET /deployments is k8s-live and never carries a Deployment row's real
# id (it reads straight off the Kubernetes API, keyed by name); the two
# hardcoded core services in GET /models/status were never Deployment
# rows to begin with. Neither can be granted a TeamModelPermission
# (deployment_id is a real FK into the deployments table), so /admin/
# teams-page's "add model access" dropdown needs an endpoint that
# actually returns that id — this is that endpoint, not a duplicate of
# either of the two above.
@app.get("/admin/deployment-registry")
def admin_deployment_registry(authorization: str = fastapi.Header(None)):
    from backend.app.database import SessionLocal
    from backend.app.services.auth import decode_token
    from backend.app.db.models import User, Deployment
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(authorization.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.id == int(payload["sub"])).first()
        if not admin or not admin.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        deployments = db.query(Deployment).all()
        return [{
            "id": d.id,
            "name": d.name,
            "model_name": d.model_name,
            "task_type": d.task_type,
            "model_type": d.model_type,
            "status": d.status,
            "is_active": d.is_active,
        } for d in deployments]
    finally:
        db.close()

@app.get("/auth/login-page")
def login_page_legacy_redirect():
    # Legacy route — the email/password login form this used to serve
    # doesn't match the username/password auth contract. Preserve the URL
    # for anyone with it bookmarked, but send them to the real page.
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Log in — Vela</title>
<style>
  /* Self-contained, like the landing page (/) — this is its natural
     continuation, one step before entering the app, so it reuses the
     same off-white/warm background, technical grid and constellation
     canvas rather than the authenticated app's dark design system. */
  :root{
    --bg:#f7f6f3; --ink:#0a0a0f; --sub:#5c5c66; --line:#d8d6cf;
    --accent:#0ea5e9; --accent-hover:#0284c7; --danger:#dc2626;
  }
  *{box-sizing:border-box}
  html{height:100%}
  body{
    margin:0; min-height:100vh; position:relative;
    font-family:ui-monospace,"JetBrains Mono","SFMono-Regular",Menlo,Consolas,monospace;
    background:var(--bg); color:var(--ink);
    display:flex; align-items:center; justify-content:center; padding:1.5rem;
  }
  .grid{position:absolute; inset:0; opacity:.5;
    background-image:
      linear-gradient(var(--line) 1px, transparent 1px),
      linear-gradient(90deg, var(--line) 1px, transparent 1px);
    background-size:56px 56px;
    -webkit-mask-image:radial-gradient(ellipse at 50% 40%, #000 0%, transparent 72%);
            mask-image:radial-gradient(ellipse at 50% 40%, #000 0%, transparent 72%);
  }
  /* Constellation — same live canvas network as the landing page (see /):
     ~40 nodes drifting at .3px/frame, bouncing off the edges, connecting
     to nearby nodes as they pass within ~150px. */
  .graphic{position:absolute; inset:0; display:block; width:100%; height:100%; opacity:.35; pointer-events:none}

  .auth-card{
    position:relative; z-index:1; width:100%; max-width:380px;
    background:#ffffff; border-radius:12px; padding:2.2rem 1.9rem;
    box-shadow:0 12px 32px rgba(10,10,15,.1), 0 2px 8px rgba(10,10,15,.06);
  }
  .auth-brand{display:flex; align-items:center; justify-content:center; gap:.5rem; margin-bottom:.6rem}
  .auth-brand-mark{width:1.15em; height:1.15em; flex-shrink:0}
  .auth-brand-name{font-size:1.15rem; font-weight:800; letter-spacing:.04em; color:var(--ink)}
  .auth-subtitle{text-align:center; font-size:.82rem; color:var(--sub); margin:0 0 1.7rem}

  .field{display:flex; flex-direction:column; gap:.35rem; margin-bottom:1rem}
  .field-label{font-size:.72rem; color:var(--sub); text-transform:uppercase; letter-spacing:.06em}
  .input{
    font:inherit; font-size:.85rem; color:var(--ink);
    background:#ffffff; border:1px solid var(--line); border-radius:6px;
    padding:.6rem .7rem; width:100%;
  }
  .input::placeholder{color:#9a9aa0}
  .input:hover{border-color:#b8b6ae}
  .input:focus-visible{outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgba(14,165,233,.18)}

  .field-error{font-size:.74rem; color:var(--danger); min-height:1.1em; margin-bottom:.5rem}

  .btn-primary{
    display:flex; align-items:center; justify-content:center; width:100%;
    background:var(--accent); color:#fff; border:1px solid var(--accent);
    padding:.68rem 1rem; border-radius:6px; font:inherit; font-size:.85rem; font-weight:600;
    cursor:pointer; letter-spacing:.02em;
  }
  .btn-primary:hover:not(:disabled){background:var(--accent-hover); border-color:var(--accent-hover)}
  .btn-primary:disabled{opacity:.6; cursor:not-allowed}

  .auth-footer-link{text-align:center; margin-top:1.4rem; font-size:.72rem; color:var(--sub)}
</style>
</head>
<body>
  <div class="grid" aria-hidden="true"></div>
  <canvas class="graphic" id="constellation" aria-hidden="true"></canvas>

  <div class="auth-card">
    <div class="auth-brand">
      <svg class="auth-brand-mark" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 20 L12 6 L18 20 Z" fill="var(--ink)" opacity=".12"/>
        <path d="M4 20 L12 3 L12 20 Z" fill="#0ea5e9"/>
        <line x1="2.5" y1="20.5" x2="19.5" y2="20.5" stroke="var(--ink)" stroke-width="1.4" stroke-linecap="round"/>
      </svg>
      <span class="auth-brand-name">VELA</span>
    </div>
    <p class="auth-subtitle">Sign in to your workspace</p>

    <form id="login-form" novalidate>
      <div class="field">
        <label class="field-label" for="username">Username</label>
        <input class="input" type="text" id="username" name="username" autocomplete="username" autofocus required>
      </div>
      <div class="field">
        <label class="field-label" for="password">Password</label>
        <input class="input" type="password" id="password" name="password" autocomplete="current-password" required>
      </div>
      <div class="field-error" id="error" role="alert"></div>
      <button class="btn-primary" type="submit" id="submit-btn">Log in</button>
    </form>

    <div class="auth-footer-link">Accounts are created by an administrator.</div>
  </div>

<script src="/static/js/api.js"></script>
<script>
(function(){
  // Constellation — identical to the landing page's (see GET /): ~40
  // nodes drifting in random directions, bouncing off the viewport
  // edges, with connections drawn dynamically between any two nodes
  // within ~150px of each other each frame.
  var canvas = document.getElementById('constellation');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');

  var NODE_COUNT = 40;
  var MAX_DIST = 150;
  var SPEED = 0.3;
  var NODE_COLOR = '30, 41, 59'; // dark navy/slate (#1e293b), rgb triplet for rgba()

  var DPR = window.devicePixelRatio || 1;
  var W = 0, H = 0;
  var nodes = [];

  function rand(min, max){ return min + Math.random() * (max - min); }

  function resize(){
    W = canvas.offsetWidth;
    H = canvas.offsetHeight;
    canvas.width = Math.max(1, Math.round(W * DPR));
    canvas.height = Math.max(1, Math.round(H * DPR));
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function seed(){
    nodes = [];
    for (var i = 0; i < NODE_COUNT; i++) {
      var angle = rand(0, Math.PI * 2);
      nodes.push({
        x: rand(0, W),
        y: rand(0, H),
        vx: Math.cos(angle) * SPEED,
        vy: Math.sin(angle) * SPEED,
        r: rand(1.4, 3)
      });
    }
  }

  function step(){
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      n.x += n.vx;
      n.y += n.vy;
      if (n.x <= 0 || n.x >= W) { n.vx *= -1; n.x = Math.min(W, Math.max(0, n.x)); }
      if (n.y <= 0 || n.y >= H) { n.vy *= -1; n.y = Math.min(H, Math.max(0, n.y)); }
    }
  }

  function draw(){
    ctx.clearRect(0, 0, W, H);
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var a = nodes[i], b = nodes[j];
        var dx = a.x - b.x, dy = a.y - b.y;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < MAX_DIST) {
          ctx.strokeStyle = 'rgba(' + NODE_COLOR + ',' + ((1 - dist / MAX_DIST) * 0.5) + ')';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }
    ctx.fillStyle = 'rgba(' + NODE_COLOR + ', 0.85)';
    for (var k = 0; k < nodes.length; k++) {
      var node = nodes[k];
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  var reduceMotion = false;
  try { reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  function loop(){
    step();
    draw();
    requestAnimationFrame(loop);
  }

  resize();
  seed();
  draw();
  if (!reduceMotion) { requestAnimationFrame(loop); }

  var resizeTimer;
  window.addEventListener('resize', function(){
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function(){
      resize();
      seed();
      draw();
    }, 150);
  });
})();
</script>
<script>
  function destinationFor(user) {
    if (user.force_password_change) return '/change-password';
    return user.is_admin ? '/admin' : '/app';
  }

  // If we already hold a valid session, skip the form entirely.
  (async function bootstrap() {
    if (!Api.isAuthed()) return;
    try {
      const user = await Api.me();
      window.location.href = destinationFor(user);
    } catch (e) {
      Api.clearToken();
    }
  })();

  const form = document.getElementById('login-form');
  const errorEl = document.getElementById('error');
  const submitBtn = document.getElementById('submit-btn');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errorEl.textContent = '';
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    if (!username || !password) {
      errorEl.textContent = 'Enter your username and password.';
      return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = 'Logging in…';
    try {
      // Raw fetch, not Api.request — a 401 here is a normal "wrong
      // credentials" outcome we want to show inline, not the global
      // "session expired, go to /login" redirect (we're already here).
      const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        errorEl.textContent = data.detail || 'Login failed.';
        return;
      }
      Api.setToken(data.token);
      window.location.href = destinationFor(data.user);
    } catch (e) {
      errorEl.textContent = 'Network error — is the API reachable?';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Log in';
    }
  });
</script>
</body>
</html>"""


@app.get("/change-password", response_class=HTMLResponse)
def change_password_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Change password — Vela</title>
<style>
  /* Self-contained, like the landing page (/) and /login — same
     off-white/warm background, technical grid and constellation canvas
     rather than the authenticated app's dark design system. */
  :root{
    --bg:#f7f6f3; --ink:#0a0a0f; --sub:#5c5c66; --line:#d8d6cf;
    --accent:#0ea5e9; --accent-hover:#0284c7; --danger:#dc2626;
    --warn-bg:#fffbeb; --warn-border:#fde68a; --warn-ink:#92660a;
  }
  *{box-sizing:border-box}
  html{height:100%}
  body{
    margin:0; min-height:100vh; position:relative;
    font-family:ui-monospace,"JetBrains Mono","SFMono-Regular",Menlo,Consolas,monospace;
    background:var(--bg); color:var(--ink);
    display:flex; align-items:center; justify-content:center; padding:1.5rem;
  }
  .grid{position:absolute; inset:0; opacity:.5;
    background-image:
      linear-gradient(var(--line) 1px, transparent 1px),
      linear-gradient(90deg, var(--line) 1px, transparent 1px);
    background-size:56px 56px;
    -webkit-mask-image:radial-gradient(ellipse at 50% 40%, #000 0%, transparent 72%);
            mask-image:radial-gradient(ellipse at 50% 40%, #000 0%, transparent 72%);
  }
  /* Constellation — same live canvas network as the landing page (see /):
     ~40 nodes drifting at .3px/frame, bouncing off the edges, connecting
     to nearby nodes as they pass within ~150px. */
  .graphic{position:absolute; inset:0; display:block; width:100%; height:100%; opacity:.35; pointer-events:none}

  .auth-card{
    position:relative; z-index:1; width:100%; max-width:380px;
    background:#ffffff; border-radius:12px; padding:2.2rem 1.9rem;
    box-shadow:0 12px 32px rgba(10,10,15,.1), 0 2px 8px rgba(10,10,15,.06);
  }
  .auth-brand{display:flex; align-items:center; justify-content:center; gap:.5rem; margin-bottom:.6rem}
  .auth-brand-mark{width:1.15em; height:1.15em; flex-shrink:0}
  .auth-brand-name{font-size:1.15rem; font-weight:800; letter-spacing:.04em; color:var(--ink)}
  .auth-subtitle{text-align:center; font-size:.82rem; color:var(--sub); margin:0 0 1.4rem}

  .alert-warning{
    display:flex; gap:.6rem; align-items:flex-start;
    background:var(--warn-bg); border:1px solid var(--warn-border); color:var(--warn-ink);
    border-radius:8px; padding:.7rem .8rem; margin-bottom:1rem; font-size:.78rem; line-height:1.5;
  }
  .alert-title{font-weight:700; margin-bottom:2px}

  .field{display:flex; flex-direction:column; gap:.35rem; margin-bottom:1rem}
  .field-label{font-size:.72rem; color:var(--sub); text-transform:uppercase; letter-spacing:.06em}
  .input{
    font:inherit; font-size:.85rem; color:var(--ink);
    background:#ffffff; border:1px solid var(--line); border-radius:6px;
    padding:.6rem .7rem; width:100%;
  }
  .input::placeholder{color:#9a9aa0}
  .input:hover{border-color:#b8b6ae}
  .input:focus-visible{outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgba(14,165,233,.18)}

  .field-error{font-size:.74rem; color:var(--danger); min-height:1.1em; margin-bottom:.5rem}

  .btn-primary{
    display:flex; align-items:center; justify-content:center; width:100%;
    background:var(--accent); color:#fff; border:1px solid var(--accent);
    padding:.68rem 1rem; border-radius:6px; font:inherit; font-size:.85rem; font-weight:600;
    cursor:pointer; letter-spacing:.02em;
  }
  .btn-primary:hover:not(:disabled){background:var(--accent-hover); border-color:var(--accent-hover)}
  .btn-primary:disabled{opacity:.6; cursor:not-allowed}

  .auth-footer-link{text-align:center; margin-top:1.4rem; font-size:.72rem; color:var(--sub)}
  .auth-footer-link a{color:var(--accent); text-decoration:none; border-bottom:1px solid transparent}
  .auth-footer-link a:hover{border-bottom-color:var(--accent)}

  .auth-loading{position:relative; z-index:1; color:var(--sub); font-size:.85rem}
</style>
</head>
<body>
  <div class="grid" aria-hidden="true"></div>
  <canvas class="graphic" id="constellation" aria-hidden="true"></canvas>

  <div class="auth-card" id="page-root" hidden>
    <div class="auth-brand">
      <svg class="auth-brand-mark" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 20 L12 6 L18 20 Z" fill="var(--ink)" opacity=".12"/>
        <path d="M4 20 L12 3 L12 20 Z" fill="#0ea5e9"/>
        <line x1="2.5" y1="20.5" x2="19.5" y2="20.5" stroke="var(--ink)" stroke-width="1.4" stroke-linecap="round"/>
      </svg>
      <span class="auth-brand-name">VELA</span>
    </div>
    <p class="auth-subtitle" id="subtitle">Change your password</p>

    <div class="alert-warning" id="forced-banner" style="display:none">
      <div>
        <div class="alert-title">Password change required</div>
        <div>An administrator set a temporary password for your account. Choose a new one to continue.</div>
      </div>
    </div>

    <form id="pw-form" novalidate>
      <div class="field">
        <label class="field-label" for="new-password">New password</label>
        <input class="input" type="password" id="new-password" autocomplete="new-password" required minlength="8">
      </div>
      <div class="field">
        <label class="field-label" for="confirm-password">Confirm new password</label>
        <input class="input" type="password" id="confirm-password" autocomplete="new-password" required minlength="8">
      </div>
      <div class="field-error" id="error" role="alert"></div>
      <button class="btn-primary" type="submit" id="submit-btn">Set new password</button>
    </form>

    <div class="auth-footer-link" id="cancel-link-wrap" style="display:none">
      <a href="#" id="cancel-link">Cancel</a>
    </div>
  </div>
  <div class="auth-loading" id="loading-root">Loading…</div>

<script src="/static/js/api.js"></script>
<script>
(function(){
  // Constellation — identical to the landing page's (see GET /): ~40
  // nodes drifting in random directions, bouncing off the viewport
  // edges, with connections drawn dynamically between any two nodes
  // within ~150px of each other each frame.
  var canvas = document.getElementById('constellation');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');

  var NODE_COUNT = 40;
  var MAX_DIST = 150;
  var SPEED = 0.3;
  var NODE_COLOR = '30, 41, 59'; // dark navy/slate (#1e293b), rgb triplet for rgba()

  var DPR = window.devicePixelRatio || 1;
  var W = 0, H = 0;
  var nodes = [];

  function rand(min, max){ return min + Math.random() * (max - min); }

  function resize(){
    W = canvas.offsetWidth;
    H = canvas.offsetHeight;
    canvas.width = Math.max(1, Math.round(W * DPR));
    canvas.height = Math.max(1, Math.round(H * DPR));
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }

  function seed(){
    nodes = [];
    for (var i = 0; i < NODE_COUNT; i++) {
      var angle = rand(0, Math.PI * 2);
      nodes.push({
        x: rand(0, W),
        y: rand(0, H),
        vx: Math.cos(angle) * SPEED,
        vy: Math.sin(angle) * SPEED,
        r: rand(1.4, 3)
      });
    }
  }

  function step(){
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      n.x += n.vx;
      n.y += n.vy;
      if (n.x <= 0 || n.x >= W) { n.vx *= -1; n.x = Math.min(W, Math.max(0, n.x)); }
      if (n.y <= 0 || n.y >= H) { n.vy *= -1; n.y = Math.min(H, Math.max(0, n.y)); }
    }
  }

  function draw(){
    ctx.clearRect(0, 0, W, H);
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var a = nodes[i], b = nodes[j];
        var dx = a.x - b.x, dy = a.y - b.y;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < MAX_DIST) {
          ctx.strokeStyle = 'rgba(' + NODE_COLOR + ',' + ((1 - dist / MAX_DIST) * 0.5) + ')';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }
    ctx.fillStyle = 'rgba(' + NODE_COLOR + ', 0.85)';
    for (var k = 0; k < nodes.length; k++) {
      var node = nodes[k];
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  var reduceMotion = false;
  try { reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}

  function loop(){
    step();
    draw();
    requestAnimationFrame(loop);
  }

  resize();
  seed();
  draw();
  if (!reduceMotion) { requestAnimationFrame(loop); }

  var resizeTimer;
  window.addEventListener('resize', function(){
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function(){
      resize();
      seed();
      draw();
    }, 150);
  });
})();
</script>
<script>
  let currentUser = null;

  function destinationFor(user) {
    return user.is_admin ? '/admin' : '/app';
  }

  (async function init() {
    if (!Api.isAuthed()) { window.location.href = '/login'; return; }
    try {
      currentUser = await Api.me();
    } catch (e) {
      window.location.href = '/login';
      return;
    }
    document.getElementById('loading-root').hidden = true;
    document.getElementById('page-root').hidden = false;

    if (currentUser.force_password_change) {
      document.getElementById('forced-banner').style.display = 'flex';
      document.getElementById('subtitle').textContent = 'Set a new password to continue';
    } else {
      document.getElementById('cancel-link-wrap').style.display = 'block';
      document.getElementById('cancel-link').href = destinationFor(currentUser);
    }
  })();

  const form = document.getElementById('pw-form');
  const errorEl = document.getElementById('error');
  const submitBtn = document.getElementById('submit-btn');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errorEl.textContent = '';
    const pw = document.getElementById('new-password').value;
    const confirm = document.getElementById('confirm-password').value;
    if (pw.length < 8) {
      errorEl.textContent = 'Password must be at least 8 characters.';
      return;
    }
    if (pw !== confirm) {
      errorEl.textContent = 'Passwords do not match.';
      return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving…';
    try {
      await Api.post('/auth/change-password', { new_password: pw });
      window.location.href = destinationFor(currentUser);
    } catch (err) {
      errorEl.textContent = err.message || 'Could not change password.';
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Set new password';
    }
  });
</script>
</body>
</html>"""

@app.get("/workspaces-page", response_class=HTMLResponse)
def workspaces_page():
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Workspaces</title>
<style>
  body{font-family:monospace;background:#0a0a0f;color:#e0e0e0;padding:2rem;max-width:800px;margin:0 auto}
  h1{color:#7eb8f7;border-bottom:1px solid #222;padding-bottom:.5rem}
  .card{background:#111;border:1px solid #222;border-radius:8px;padding:1rem;margin:.5rem 0;cursor:pointer}
  .card:hover{border-color:#7eb8f7}
  input{background:#0a0a0f;border:1px solid #333;color:#e0e0e0;padding:.4rem .6rem;border-radius:4px;font-family:monospace;width:100%;margin:.3rem 0;box-sizing:border-box}
  button{background:#1a3a5c;color:#7eb8f7;border:1px solid #2a5a8c;padding:.4rem 1rem;border-radius:4px;cursor:pointer;font-family:monospace}
  button:hover{background:#2a5a8c}
  h2{font-size:.85rem;color:#555;text-transform:uppercase;letter-spacing:.1em;margin:1.5rem 0 .5rem}
  .logout{float:right;font-size:.8rem;color:#555;cursor:pointer}
  .logout:hover{color:#f77e7e}
</style></head>
<body>
  <h1>&#9881; Workspaces <span class="logout" onclick="logout()">Log out</span></h1>
  <div id="user-info" style="color:#555;font-size:.85rem;margin-bottom:1rem"></div>
  <div id="workspaces"></div>
  <h2>Create new workspace</h2>
  <div style="background:#111;border:1px solid #222;border-radius:8px;padding:1rem">
    <input type="text" id="ws-name" placeholder="Workspace name">
    <input type="text" id="ws-desc" placeholder="Description (optional)">
    <button onclick="createWorkspace()">Create workspace</button>
    <div id="ws-error" style="color:#f77e7e;font-size:.8rem;margin-top:.3rem"></div>
  </div>
<script>
  const token = localStorage.getItem('aodp_token');
  if(!token) window.location.href='/auth/login-page';
  const headers = {'Content-Type':'application/json','Authorization':'Bearer '+token};

  async function load(){
    const me = await fetch('/auth/me',{headers});
    if(!me.ok){logout();return;}
    const u = await me.json();
    document.getElementById('user-info').textContent = 'Logged in as '+u.name+' ('+u.email+')';
    const r = await fetch('/workspaces',{headers});
    const ws = await r.json();
    const el = document.getElementById('workspaces');
    if(ws.length===0){el.innerHTML='<div style="color:#555;font-style:italic">No workspaces yet — create one below.</div>';return;}
    el.innerHTML = ws.map(w=>'<div class="card" style="cursor:pointer" onclick="goToWorkspace('+w.id+')">'+'<div style="font-weight:500;color:#e0e0e0">'+w.name+'</div>'+'<div style="font-size:.8rem;color:#555">'+w.description+'</div>'+'</div>').join('');
  }

  async function createWorkspace(){
    const name=document.getElementById('ws-name').value.trim();
    const description=document.getElementById('ws-desc').value.trim();
    if(!name){document.getElementById('ws-error').textContent='Name required';return;}
    const r=await fetch('/workspaces',{method:'POST',headers,body:JSON.stringify({name,description})});
    const d=await r.json();
    if(r.ok) window.location.href='/workspace/'+d.id;
    else document.getElementById('ws-error').textContent=d.detail||'Failed';
  }

  function logout(){localStorage.removeItem('aodp_token');window.location.href='/auth/login-page';}
  function goToWorkspace(id){window.location.href='/workspace/'+id;}
  load();
</script></body></html>"""

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>AI-Operated Model Deployment Platform</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
  <style>
    *{box-sizing:border-box}
    body{font-family:monospace;background:#0a0a0f;color:#e0e0e0;padding:1.5rem;margin:0 auto;max-width:960px}
    h1{font-size:1.2rem;color:#7eb8f7;border-bottom:1px solid #1a1a2a;padding-bottom:.5rem;margin-bottom:1.2rem}
    h2{font-size:.75rem;color:#555;text-transform:uppercase;letter-spacing:.1em;margin:1.2rem 0 .5rem}
    .card{background:#111;border:1px solid #1e1e2e;border-radius:8px;padding:.9rem 1rem;margin-bottom:.6rem}
    .card.online{border-left:3px solid #7ef7a0}.card.offline{border-left:3px solid #f77e7e}
    .card.starting{border-left:3px solid #f7c97e}.card.running{border-left:3px solid #7ef7a0}
    .card-name{font-size:.88rem;font-weight:500;color:#e0e0e0;margin-bottom:.2rem}
    .card-sub{font-size:.72rem;color:#555;margin-bottom:.4rem}
    .badge{display:inline-block;padding:2px 7px;border-radius:3px;font-size:.68rem;font-weight:500;margin-right:3px}
    .badge.online,.badge.running{background:#1a3a1a;color:#7ef7a0}
    .badge.offline{background:#3a1a1a;color:#f77e7e}.badge.starting{background:#3a2a1a;color:#f7c97e}
    .metrics-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.6rem;margin-bottom:.6rem}
    .metric-card{background:#0d0d18;border:1px solid #1e1e2e;border-radius:8px;padding:.7rem .9rem;text-align:center}
    .metric-val{font-size:1.3rem;font-weight:500;color:#e0e0e0;margin:0}
    .metric-lbl{font-size:.68rem;color:#555;margin:.2rem 0 0;text-transform:uppercase;letter-spacing:.05em}
    .gauge-row{display:grid;grid-template-columns:1fr 1fr;gap:.6rem;margin-bottom:.6rem}
    .gauge-card{background:#0d0d18;border:1px solid #1e1e2e;border-radius:8px;padding:.7rem .9rem}
    .gauge-label{font-size:.72rem;color:#555;margin-bottom:.4rem;text-transform:uppercase;letter-spacing:.05em}
    .gauge-bar-bg{background:#1a1a2a;border-radius:4px;height:8px;overflow:hidden;margin-bottom:.3rem}
    .gauge-bar{height:8px;border-radius:4px;transition:width .6s ease}
    .gauge-val{font-size:.8rem;color:#e0e0e0}
    .chart-wrap{background:#0d0d18;border:1px solid #1e1e2e;border-radius:8px;padding:.7rem .9rem;margin-bottom:.6rem}
    .chart-title{font-size:.72rem;color:#555;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem}
    .models-grid{display:grid;grid-template-columns:1fr 1fr;gap:.6rem}
    .row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-bottom:.4rem}
    select,input[type=text]{background:#0a0a0f;border:1px solid #2a2a3a;color:#e0e0e0;padding:.35rem .6rem;border-radius:4px;font-family:monospace;font-size:.82rem;flex:1;min-width:130px}
    button{background:#1a3a5c;color:#7eb8f7;border:1px solid #2a5a8c;padding:.35rem .9rem;border-radius:4px;cursor:pointer;font-family:monospace;font-size:.82rem;white-space:nowrap}
    button:hover{background:#2a5a8c}button:disabled{opacity:.4;cursor:not-allowed}
    #deploy-status,#tester-result{font-size:.8rem;color:#888;min-height:1.2rem;padding:.3rem 0;white-space:pre-wrap}
    #tester-result{background:#0a0a0f;border-radius:4px;padding:.4rem .6rem;color:#ccc}
    #summary-sub{font-size:.68rem;color:#444;margin-bottom:.3rem}
    #summary-box{border-left:3px solid #7eb8f7;padding:.6rem .9rem;font-size:.82rem;line-height:1.6;color:#ccc;background:#0d0d14;border-radius:0 4px 4px 0;min-height:2rem}
    #tl-status{color:#555;font-size:.75rem;margin-bottom:.4rem}
    #timeline{list-style:none;padding:0;margin:0;max-height:280px;overflow-y:auto}
    #timeline li{display:flex;gap:.6rem;align-items:baseline;padding:.25rem 0;border-bottom:1px solid #111;font-size:.78rem}
    .ts{color:#444;min-width:150px;flex-shrink:0}
    .ev{display:inline-block;padding:.1rem .4rem;border-radius:3px;font-size:.68rem;min-width:72px;text-align:center;flex-shrink:0}
    .ev.deploy{background:#1a3a5c;color:#7eb8f7}.ev.drift{background:#3a1a1a;color:#f77e7e}
    .ev.latency_p95{background:#1a3a1a;color:#7ef7a0}.detail{color:#777}
  </style>
</head>
<body>
  <h1>&#9881; AI-Operated Model Deployment Platform</h1>

  <h2>Live metrics</h2>
  <div class="metrics-grid">
    <div class="metric-card"><p class="metric-val" id="m-rate">—</p><p class="metric-lbl">Predictions / min</p></div>
    <div class="metric-card"><p class="metric-val" id="m-latency">—</p><p class="metric-lbl">p95 latency ms</p></div>
    <div class="metric-card"><p class="metric-val" id="m-drift">—</p><p class="metric-lbl">Drift score</p></div>
    <div class="metric-card"><p class="metric-val" id="m-total">—</p><p class="metric-lbl">Total predictions</p></div>
  </div>
  <div class="gauge-row">
    <div class="gauge-card">
      <div class="gauge-label">Node CPU usage</div>
      <div class="gauge-bar-bg"><div class="gauge-bar" id="cpu-bar" style="width:0%;background:#7eb8f7"></div></div>
      <div class="gauge-val" id="cpu-val">—</div>
    </div>
    <div class="gauge-card">
      <div class="gauge-label">Node memory usage</div>
      <div class="gauge-bar-bg"><div class="gauge-bar" id="mem-bar" style="width:0%;background:#7ef7a0"></div></div>
      <div class="gauge-val" id="mem-val">—</div>
    </div>
  </div>
  <div class="chart-wrap">
    <div class="chart-title">Drift score — last 2 hours</div>
    <canvas id="drift-chart" height="80"></canvas>
  </div>
  <div class="chart-wrap" id="drift-details-wrap" style="display:none">
    <div class="chart-title">Population-level drift breakdown</div>
    <div id="drift-details-content"></div>
  </div>

  <h2>Deployed models</h2>
  <div id="core-models" class="models-grid">
    <div class="card" id="card-1"><div class="card-name">Loading...</div></div>
    <div class="card" id="card-2"><div class="card-name">Loading...</div></div>
  </div>
  <div id="platform-models" style="display:grid;grid-template-columns:1fr 1fr;gap:.6rem;margin-top:.6rem"></div>

  <h2>Deploy new model</h2>
  <div class="card">
    <div class="row">
      <input type="text" id="deploy-model-name" placeholder="HuggingFace model name">
      <select id="deploy-task" style="flex:0 0 auto;min-width:120px">
        <option value="sentiment-analysis">Sentiment</option>
        <option value="zero-shot-classification">Zero-Shot</option>
      </select>
    </div>
    <div class="row">
      <input type="text" id="deploy-display-name" placeholder="deployment-name (lowercase, no spaces)">
      <button onclick="deployModel()">Deploy via GitHub Actions</button>
    </div>
    <div id="deploy-status"></div>
  </div>

  <h2>Live prediction tester</h2>
  <div class="card">
    <div class="row">
      <select id="model-select" style="flex:0 0 auto;min-width:220px">
        <option value="1">Model 1 — DistilBERT Sentiment</option>
        <option value="2">Model 2 — distilbart Zero-Shot</option>
      </select>
      <input type="text" id="pred-input" value="The new product launch exceeded all expectations">
      <button id="pred-btn" onclick="predict()">Predict</button>
    </div>
    <div id="tester-result">Result will appear here</div>
  </div>

  <h2>LLM summary</h2>
  <div id="summary-sub">Generated by Groq &middot; openai/gpt-oss-20b &middot; auto-refresh 30s</div>
  <div id="summary-box">Loading summary...</div>

  <h2>Operations timeline <span id="tl-status"></span></h2>
  <ul id="timeline"></ul>

  <script>
    const W=360;
    let driftChart=null;
    function fmt(ts){return new Date(ts*1000).toLocaleString();}
    function fmtN(n,dec=1){return (isNaN(n)||n===null||n===undefined)?'—':Number(n).toFixed(dec);}

    function initChart(){
      const ctx=document.getElementById('drift-chart').getContext('2d');
      driftChart=new Chart(ctx,{
        type:'line',
        data:{labels:[],datasets:[{label:'Drift',data:[],borderColor:'#f77e7e',backgroundColor:'rgba(247,126,126,0.08)',borderWidth:1.5,pointRadius:0,fill:true,tension:0.3}]},
        options:{responsive:true,plugins:{legend:{display:false}},scales:{x:{display:false},y:{min:0,max:1,ticks:{color:'#555',font:{size:10}},grid:{color:'#1a1a2a'}}}}
      });
    }

    async function loadMetrics(){
      try{
        const r=await fetch('/metrics-summary');
        const d=await r.json();
        document.getElementById('m-rate').textContent=fmtN(d.prediction_rate_5m,1);
        document.getElementById('m-latency').textContent=d.latency_p95>0?fmtN(d.latency_p95*1000,0):'—';
        document.getElementById('m-drift').textContent=fmtN(d.drift_score,3);
        document.getElementById('m-total').textContent=Math.round(d.predictions_total)||'—';
        const cpu=Math.round(d.node_cpu_percent||0);
        const mu=d.node_memory_used_gb||0;
        const mt=d.node_memory_total_gb||12;
        const mp=Math.round((mu/mt)*100);
        document.getElementById('cpu-bar').style.width=cpu+'%';
        document.getElementById('cpu-val').textContent=cpu+'%';
        document.getElementById('mem-bar').style.width=mp+'%';
        document.getElementById('mem-val').textContent=fmtN(mu,1)+'GB / '+fmtN(mt,1)+'GB ('+mp+'%)';
        document.getElementById('mem-bar').style.background=mp>85?'#f77e7e':mp>65?'#f7c97e':'#7ef7a0';
        document.getElementById('cpu-bar').style.background=cpu>85?'#f77e7e':cpu>65?'#f7c97e':'#7eb8f7';
        if(driftChart&&d.drift_history&&d.drift_history.length){
          driftChart.data.labels=d.drift_history.map(p=>new Date(p[0]*1000).toLocaleTimeString());
          driftChart.data.datasets[0].data=d.drift_history.map(p=>p[1]);
          driftChart.update('none');
        }
        if(d.drift_details&&d.drift_details.columns&&d.drift_details.columns.length>0){
          const wrap=document.getElementById('drift-details-wrap');
          const content=document.getElementById('drift-details-content');
          wrap.style.display='block';
          content.innerHTML=d.drift_details.columns.map(c=>{
            const color=c.drifted?'#f77e7e':'#7ef7a0';
            const pct=Math.round((1-c.p_value)*100);
            return '<div style="display:flex;align-items:center;gap:.5rem;margin:.3rem 0;font-size:.8rem">'+
              '<span style="min-width:120px;color:#ccc">'+c.column+'</span>'+
              '<div style="flex:1;background:#1a1a2a;border-radius:3px;height:8px">'+
              '<div style="width:'+pct+'%;background:'+color+';height:8px;border-radius:3px;transition:width .5s"></div></div>'+
              '<span style="min-width:60px;color:'+color+';text-align:right">'+
              (c.drifted?'DRIFTED':'stable')+' p='+c.p_value+'</span></div>';
          }).join('');
        }
      }catch(e){console.error('metrics',e);}
    }

    async function loadModels(){
      try{
        const [sr,dr]=await Promise.all([fetch('/models/status'),fetch('/deployments')]);
        const models=await sr.json();
        const platform=await dr.json();
        models.forEach(m=>{
          const c=document.getElementById('card-'+m.id);
          if(!c)return;
          c.className='card '+m.status;
          c.innerHTML='<div class="card-name">'+m.name+'</div><div class="card-sub">'+m.task+' &middot; '+m.model+'</div><span class="badge '+m.status+'">'+m.status.toUpperCase()+'</span>';
        });
        const pm=document.getElementById('platform-models');
        pm.innerHTML=platform.map(d=>'<div class="card '+d.status+'"><div class="card-name">'+d.name+'</div><div class="card-sub">'+d.task_type+' &middot; '+d.model_name+'</div><span class="badge '+d.status+'">'+d.status.toUpperCase()+' ('+d.ready+'/'+d.desired+')</span></div>').join('');
        const sel=document.getElementById('model-select');
        const existing=Array.from(sel.options).map(o=>o.value);
        platform.filter(d=>d.status==='running'&&!existing.includes('svc:'+d.name)).forEach(d=>{
          const opt=document.createElement('option');
          opt.value='svc:'+d.name;
          opt.textContent=d.name+' — '+d.task_type;
          sel.appendChild(opt);
        });
      }catch(e){console.error('models',e);}
    }

    async function deployModel(){
      const mn=document.getElementById('deploy-model-name').value.trim();
      const tt=document.getElementById('deploy-task').value;
      const dn=document.getElementById('deploy-display-name').value.trim();
      const st=document.getElementById('deploy-status');
      if(!mn||!dn){st.textContent='Please fill in all fields.';return;}
      if(!/^[a-z0-9-]+$/.test(dn)){st.textContent='Deployment name: lowercase, numbers, hyphens only.';return;}
      st.textContent='Triggering GitHub Actions...';
      try{
        const r=await fetch('/deploy-model',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:mn,task_type:tt,deployment_name:dn})});
        const d=await r.json();
        if(r.ok)st.textContent='Triggered! "'+dn+'" will appear in ~5-10 min.';
        else st.textContent='Error: '+(d.detail||JSON.stringify(d));
      }catch(e){st.textContent='Error: '+e;}
    }

    async function predict(){
      const btn=document.getElementById('pred-btn');
      const res=document.getElementById('tester-result');
      const text=document.getElementById('pred-input').value.trim();
      const midRaw=document.getElementById('model-select').value;
      const isSvc=midRaw.startsWith('svc:');
      const mid=isSvc?midRaw:parseInt(midRaw);
      if(!text){res.textContent='Enter some text first.';return;}
      btn.disabled=true;res.textContent='Running...';
      try{
        const body=isSvc?{text,service_name:midRaw.replace('svc:','')}:{text,model_id:mid};
        const r=await fetch('/predict-proxy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        const d=await r.json();
        if(d.all_labels&&Object.keys(d.all_labels).length>0){
          res.textContent='Top: '+d.label+' | '+Object.entries(d.all_labels).sort((a,b)=>b[1]-a[1]).map(([k,v])=>k+': '+(v*100).toFixed(1)+'%').join(' | ');
        } else {
          res.textContent='Label: '+d.label+' | Score: '+(d.score*100).toFixed(1)+'%';
        }
      }catch(e){res.textContent='Error: '+e;}
      finally{btn.disabled=false;}
    }

    document.getElementById('pred-input').addEventListener('keydown',e=>{if(e.key==='Enter')predict();});

    async function loadSummary(){
      const b=document.getElementById('summary-box');
      try{const r=await fetch('/summary?window_minutes='+W);const d=await r.json();b.textContent=d.summary||'No summary.';}
      catch(e){b.textContent='Unavailable: '+e;}
    }

    async function loadTimeline(){
      const st=document.getElementById('tl-status');
      const li=document.getElementById('timeline');
      try{
        const r=await fetch('/timeline?window_minutes='+W);
        const ev=await r.json();
        st.textContent='— '+ev.length+' events — last '+W+'min — refresh 30s';
        li.innerHTML=ev.map(e=>'<li><span class="ts">'+fmt(e.timestamp)+'</span><span class="ev '+e.type+'">'+e.type+'</span><span class="detail">'+e.detail+'</span></li>').join('');
      }catch(e){st.textContent='Error: '+e;}
    }

    async function load(){await Promise.all([loadMetrics(),loadModels(),loadSummary(),loadTimeline()]);}
    initChart();load();setInterval(load,30000);
  </script>
</body>
</html>"""
