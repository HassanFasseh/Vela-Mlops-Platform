from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from backend.app.schemas import Model
from backend.app.db.models import Base
from backend.app.database import engine
from backend.app.services.deployment import deploy_model
from backend.app.services.timeline import build_timeline
from backend.app.services.summary import generate_summary
from pydantic import BaseModel
import requests as http_requests
import os

Base.metadata.create_all(bind=engine)
app = FastAPI()

MODEL_SERVICE_URL   = "http://model-service.default.svc.cluster.local"
MODEL_SERVICE_2_URL = "http://model-service-2.default.svc.cluster.local"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")

class PredictRequest(BaseModel):
    text: str
    model_id: int = 1
    labels: list[str] = ["technology", "sports", "politics", "entertainment", "business"]

class DeployModelRequest(BaseModel):
    model_name: str
    task_type: str
    deployment_name: str

@app.get("/")
def root():
    return {"message": "Hello World"}

@app.post("/deploy")
def deploy(model: Model):
    deploy_model(model)
    return {"status": "deployed", "model": model.name}

@app.get("/timeline")
def timeline(window_minutes: int = 360):
    return build_timeline(window_minutes)

@app.get("/summary")
def summary(window_minutes: int = 360):
    events = build_timeline(window_minutes)
    return {"summary": generate_summary(events)}

@app.get("/models/status")
def models_status():
    statuses = []
    for model_id, url, name, task in [
        (1, MODEL_SERVICE_URL, "DistilBERT Sentiment", "sentiment-analysis"),
        (2, MODEL_SERVICE_2_URL, "distilbart-mnli Zero-Shot", "zero-shot-classification"),
    ]:
        try:
            r = http_requests.get(f"{url}/health", timeout=3)
            health = r.json()
            statuses.append({
                "id": model_id, "name": name, "task": task,
                "status": "online", "model": health.get("model", "unknown")
            })
        except Exception:
            statuses.append({
                "id": model_id, "name": name, "task": task,
                "status": "offline", "model": "unavailable"
            })
    return statuses

@app.post("/predict-proxy")
def predict_proxy(req: PredictRequest):
    url = MODEL_SERVICE_URL if req.model_id == 1 else MODEL_SERVICE_2_URL
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
        return {"status": "triggered", "deployment_name": req.deployment_name}
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

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>AI-Operated Model Deployment Platform</title>
  <style>
    *{box-sizing:border-box}
    body{font-family:monospace;background:#0a0a0f;color:#e0e0e0;padding:2rem;margin:0 auto;max-width:1100px}
    h1{font-size:1.3rem;color:#7eb8f7;border-bottom:1px solid #222;padding-bottom:.6rem;margin-bottom:1.5rem;letter-spacing:.05em}
    h2{font-size:.85rem;color:#555;text-transform:uppercase;letter-spacing:.1em;margin:1.5rem 0 .75rem}
    #models-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem}
    .model-card{background:#111;border:1px solid #222;border-radius:6px;padding:1rem}
    .model-card.online{border-left:3px solid #7ef7a0}
    .model-card.offline{border-left:3px solid #f77e7e}
    .model-card.starting{border-left:3px solid #f7c97e}
    .model-name{font-size:.9rem;color:#e0e0e0;margin-bottom:.3rem}
    .model-task{font-size:.75rem;color:#555;margin-bottom:.5rem}
    .model-badge{display:inline-block;padding:.15rem .5rem;border-radius:3px;font-size:.7rem}
    .model-badge.online{background:#1a3a1a;color:#7ef7a0}
    .model-badge.offline{background:#3a1a1a;color:#f77e7e}
    .model-badge.starting{background:#3a2a1a;color:#f7c97e}
    #deploy-form{background:#111;border:1px solid #222;border-radius:6px;padding:1rem;margin-bottom:1rem}
    #deploy-controls{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-bottom:.5rem}
    #deploy-status{font-size:.8rem;color:#888;min-height:1.2rem}
    #tester{background:#111;border:1px solid #222;border-radius:6px;padding:1rem;margin-bottom:1.5rem}
    #tester-controls{display:flex;gap:.5rem;margin-bottom:.75rem;flex-wrap:wrap;align-items:center}
    select,input[type=text]{background:#0a0a0f;border:1px solid #333;color:#e0e0e0;padding:.4rem .6rem;border-radius:4px;font-family:monospace;font-size:.85rem}
    input[type=text]{flex:1;min-width:200px}
    button{background:#1a3a5c;color:#7eb8f7;border:1px solid #2a5a8c;padding:.4rem 1rem;border-radius:4px;cursor:pointer;font-family:monospace;font-size:.85rem}
    button:hover{background:#2a5a8c}
    button:disabled{opacity:.4;cursor:not-allowed}
    button.danger{background:#3a1a1a;color:#f77e7e;border-color:#5a2a2a}
    #tester-result{font-size:.85rem;color:#ccc;min-height:1.5rem;padding:.5rem;background:#0a0a0f;border-radius:4px;white-space:pre-wrap}
    #summary-label{font-size:.7rem;color:#555;margin-bottom:.3rem;text-transform:uppercase;letter-spacing:.05em}
    #summary-box{background:#111;border-left:3px solid #7eb8f7;padding:.75rem 1rem;margin-bottom:1.5rem;font-size:.85rem;line-height:1.6;color:#ccc;min-height:2.5rem;border-radius:0 4px 4px 0}
    #status{color:#555;font-size:.8rem;margin-bottom:.5rem}
    #timeline{list-style:none;padding:0;margin:0}
    #timeline li{display:flex;gap:1rem;align-items:baseline;padding:.35rem 0;border-bottom:1px solid #111;font-size:.82rem}
    .ts{color:#444;min-width:160px;flex-shrink:0}
    .badge{display:inline-block;padding:.1rem .5rem;border-radius:3px;font-size:.72rem;min-width:80px;text-align:center;flex-shrink:0}
    .deploy{background:#1a3a5c;color:#7eb8f7}
    .drift{background:#3a1a1a;color:#f77e7e}
    .latency_p95{background:#1a3a1a;color:#7ef7a0}
    .detail{color:#888}
  </style>
</head>
<body>
  <h1>⚙ AI-Operated Model Deployment Platform</h1>

  <h2>Deployed Models</h2>
  <div id="models-grid">
    <div class="model-card" id="card-1"><div class="model-name">Loading...</div></div>
    <div class="model-card" id="card-2"><div class="model-card" id="card-2"><div class="model-name">Loading...</div></div>
  </div>
  <div id="platform-models"></div>

  <h2>Deploy New Model</h2>
  <div id="deploy-form">
    <div id="deploy-controls">
      <input type="text" id="deploy-model-name" placeholder="HuggingFace model name (e.g. distilbert-base-uncased-finetuned-sst-2-english)" style="flex:2">
      <select id="deploy-task">
        <option value="sentiment-analysis">Sentiment Analysis</option>
        <option value="zero-shot-classification">Zero-Shot Classification</option>
      </select>
      <input type="text" id="deploy-display-name" placeholder="deployment-name (lowercase, no spaces)" style="min-width:180px">
      <button onclick="deployModel()">Deploy</button>
    </div>
    <div id="deploy-status"></div>
  </div>

  <h2>Live Prediction Tester</h2>
  <div id="tester">
    <div id="tester-controls">
      <select id="model-select">
        <option value="1">Model 1 — Sentiment Analysis</option>
        <option value="2">Model 2 — Zero-Shot Classification</option>
      </select>
      <input type="text" id="pred-input" placeholder="Type something to classify..." value="The new product launch exceeded all expectations">
      <button id="pred-btn" onclick="predict()">Predict</button>
    </div>
    <div id="tester-result">Result will appear here</div>
  </div>

  <h2>LLM Summary</h2>
  <div id="summary-label">Generated by Groq · llama-3.3-70b-versatile · auto-refresh 30s</div>
  <div id="summary-box">Loading summary...</div>

  <h2>Operations Timeline <span id="status"></span></h2>
  <ul id="timeline"></ul>

  <script>
    const W = 360;
    function fmt(ts){ return new Date(ts*1000).toLocaleString(); }

    async function loadModels(){
      try {
        const [statusR, deplR] = await Promise.all([
          fetch('/models/status'),
          fetch('/deployments')
        ]);
        const models = await statusR.json();
        const platform = await deplR.json();

        models.forEach(m => {
          const card = document.getElementById('card-'+m.id);
          if(!card) return;
          card.className = 'model-card ' + m.status;
          card.innerHTML =
            '<div class="model-name">'+m.name+'</div>'+
            '<div class="model-task">'+m.task+'</div>'+
            '<span class="model-badge '+m.status+'">'+m.status.toUpperCase()+'</span>'+
            '<div style="font-size:.75rem;color:#555;margin-top:.4rem">'+m.model+'</div>';
        });

        const pm = document.getElementById('platform-models');
        if(platform.length > 0){
          pm.innerHTML = platform.map(d =>
            '<div class="model-card '+d.status+'" style="margin-top:.5rem">'+
            '<div class="model-name">'+d.name+'</div>'+
            '<div class="model-task">'+d.task_type+' · '+d.model_name+'</div>'+
            '<span class="model-badge '+d.status+'">'+d.status.toUpperCase()+' ('+d.ready+'/'+d.desired+')</span>'+
            '</div>'
          ).join('');
        }
      } catch(err){ console.error('models status failed', err); }
    }

    async function deployModel(){
      const modelName = document.getElementById('deploy-model-name').value.trim();
      const taskType  = document.getElementById('deploy-task').value;
      const deplName  = document.getElementById('deploy-display-name').value.trim();
      const status    = document.getElementById('deploy-status');
      if(!modelName || !deplName){ status.textContent = 'Please fill in all fields.'; return; }
      if(!/^[a-z0-9-]+$/.test(deplName)){ status.textContent = 'Deployment name must be lowercase letters, numbers, and hyphens only.'; return; }
      status.textContent = 'Triggering GitHub Actions workflow...';
      try {
        const r = await fetch('/deploy-model', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({model_name: modelName, task_type: taskType, deployment_name: deplName})
        });
        const data = await r.json();
        if(r.ok){
          status.textContent = 'Workflow triggered! Building and deploying "'+deplName+'" — check back in 5-10 minutes.';
          setTimeout(loadModels, 30000);
        } else {
          status.textContent = 'Error: ' + (data.detail || JSON.stringify(data));
        }
      } catch(err){ status.textContent = 'Error: '+err; }
    }

    async function predict(){
      const btn = document.getElementById('pred-btn');
      const result = document.getElementById('tester-result');
      const text = document.getElementById('pred-input').value.trim();
      const modelId = parseInt(document.getElementById('model-select').value);
      if(!text){ result.textContent = 'Please enter some text first.'; return; }
      btn.disabled = true;
      result.textContent = 'Running prediction...';
      try {
        const r = await fetch('/predict-proxy', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({text, model_id: modelId})
        });
        const data = await r.json();
        if(modelId === 1){
          result.textContent = 'Label: '+data.label+'  |  Score: '+(data.score*100).toFixed(1)+'%';
        } else {
          const top = Object.entries(data.all_labels||{})
            .sort((a,b)=>b[1]-a[1])
            .map(([k,v])=>k+': '+(v*100).toFixed(1)+'%').join('  |  ');
          result.textContent = 'Top: '+data.label+'\n'+top;
        }
      } catch(err){ result.textContent = 'Error: '+err; }
      finally { btn.disabled = false; }
    }

    document.getElementById('pred-input').addEventListener('keydown', e => {
      if(e.key==='Enter') predict();
    });

    async function loadSummary(){
      const box = document.getElementById('summary-box');
      try {
        const r = await fetch('/summary?window_minutes='+W);
        const data = await r.json();
        box.textContent = data.summary || 'No summary available.';
      } catch(err){ box.textContent = 'Summary unavailable: '+err; }
    }

    async function loadTimeline(){
      const status = document.getElementById('status');
      const list = document.getElementById('timeline');
      try {
        const r = await fetch('/timeline?window_minutes='+W);
        const events = await r.json();
        status.textContent = '— '+events.length+' events — last '+W+'min — auto-refresh 30s';
        list.innerHTML = events.map(e =>
          '<li><span class="ts">'+fmt(e.timestamp)+'</span>'+
          '<span class="badge '+e.type+'">'+e.type+'</span>'+
          '<span class="detail">'+e.detail+'</span></li>'
        ).join('');
      } catch(err){ status.textContent = 'Error: '+err; }
    }

    async function load(){
      await Promise.all([loadModels(), loadSummary(), loadTimeline()]);
    }

    load();
    setInterval(load, 30000);
  </script>
</body>
</html>"""
