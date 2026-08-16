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

Base.metadata.create_all(bind=engine)
app = FastAPI()

MODEL_SERVICE_URL = "http://model-service.default.svc.cluster.local"
MODEL_SERVICE_2_URL = "http://model-service-2.default.svc.cluster.local"

class PredictRequest(BaseModel):
    text: str
    model_id: int = 1
    labels: list[str] = ["technology", "sports", "politics", "entertainment", "business"]

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

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>AI-Operated Model Deployment Platform</title>
  <style>
    *{box-sizing:border-box}
    body{font-family:monospace;background:#0a0a0f;color:#e0e0e0;padding:2rem;margin:0;max-width:1100px;margin:0 auto}
    h1{font-size:1.3rem;color:#7eb8f7;border-bottom:1px solid #222;padding-bottom:.6rem;margin-bottom:1.5rem;letter-spacing:.05em}
    h2{font-size:.85rem;color:#555;text-transform:uppercase;letter-spacing:.1em;margin:1.5rem 0 .75rem}

    /* Model status cards */
    #models-grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.5rem}
    .model-card{background:#111;border:1px solid #222;border-radius:6px;padding:1rem}
    .model-card.online{border-left:3px solid #7ef7a0}
    .model-card.offline{border-left:3px solid #f77e7e}
    .model-name{font-size:.9rem;color:#e0e0e0;margin-bottom:.3rem}
    .model-task{font-size:.75rem;color:#555;margin-bottom:.5rem}
    .model-badge{display:inline-block;padding:.15rem .5rem;border-radius:3px;font-size:.7rem}
    .model-badge.online{background:#1a3a1a;color:#7ef7a0}
    .model-badge.offline{background:#3a1a1a;color:#f77e7e}

    /* Prediction tester */
    #tester{background:#111;border:1px solid #222;border-radius:6px;padding:1rem;margin-bottom:1.5rem}
    #tester-controls{display:flex;gap:.5rem;margin-bottom:.75rem;flex-wrap:wrap;align-items:center}
    select,input[type=text]{background:#0a0a0f;border:1px solid #333;color:#e0e0e0;padding:.4rem .6rem;border-radius:4px;font-family:monospace;font-size:.85rem}
    input[type=text]{flex:1;min-width:200px}
    button{background:#1a3a5c;color:#7eb8f7;border:1px solid #2a5a8c;padding:.4rem 1rem;border-radius:4px;cursor:pointer;font-family:monospace;font-size:.85rem}
    button:hover{background:#2a5a8c}
    button:disabled{opacity:.4;cursor:not-allowed}
    #tester-result{font-size:.85rem;color:#ccc;min-height:1.5rem;padding:.5rem;background:#0a0a0f;border-radius:4px;white-space:pre-wrap}

    /* LLM Summary */
    #summary-label{font-size:.7rem;color:#555;margin-bottom:.3rem;text-transform:uppercase;letter-spacing:.05em}
    #summary-box{background:#111;border-left:3px solid #7eb8f7;padding:.75rem 1rem;margin-bottom:1.5rem;font-size:.85rem;line-height:1.6;color:#ccc;min-height:2.5rem;border-radius:0 4px 4px 0}

    /* Timeline */
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
    <div class="model-card" id="card-2"><div class="model-name">Loading...</div></div>
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

  <h2>Operations Timeline <span id="status" style="font-size:.75rem;text-transform:none;letter-spacing:0"></span></h2>
  <ul id="timeline"></ul>

  <script>
    const W = 360;

    function fmt(ts){ return new Date(ts*1000).toLocaleString(); }

    async function loadModels(){
      try {
        const r = await fetch('/models/status');
        const models = await r.json();
        models.forEach(m => {
          const card = document.getElementById('card-'+m.id);
          card.className = 'model-card ' + m.status;
          card.innerHTML =
            '<div class="model-name">' + m.name + '</div>' +
            '<div class="model-task">' + m.task + '</div>' +
            '<span class="model-badge ' + m.status + '">' + m.status.toUpperCase() + '</span>' +
            '<div style="font-size:.75rem;color:#555;margin-top:.4rem">' + m.model + '</div>';
        });
      } catch(err) { console.error('models status failed', err); }
    }

    async function predict(){
      const btn = document.getElementById('pred-btn');
      const result = document.getElementById('tester-result');
      const text = document.getElementById('pred-input').value.trim();
      const modelId = parseInt(document.getElementById('model-select').value);
      if (!text){ result.textContent = 'Please enter some text first.'; return; }
      btn.disabled = true;
      result.textContent = 'Running prediction...';
      try {
        const r = await fetch('/predict-proxy', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({text, model_id: modelId})
        });
        const data = await r.json();
        if (modelId === 1){
          result.textContent = 'Label: ' + data.label + '  |  Score: ' + (data.score*100).toFixed(1) + '%';
        } else {
          const top = Object.entries(data.all_labels)
            .sort((a,b)=>b[1]-a[1])
            .map(([k,v]) => k + ': ' + (v*100).toFixed(1) + '%')
            .join('  |  ');
          result.textContent = 'Top label: ' + data.label + '\\n' + top;
        }
      } catch(err) {
        result.textContent = 'Error: ' + err;
      } finally {
        btn.disabled = false;
      }
    }

    document.getElementById('pred-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') predict();
    });

    async function loadSummary(){
      const box = document.getElementById('summary-box');
      try {
        const r = await fetch('/summary?window_minutes='+W);
        const data = await r.json();
        box.textContent = data.summary;
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
          '<li><span class="ts">'+fmt(e.timestamp)+'</span>' +
          '<span class="badge '+e.type+'">'+e.type+'</span>' +
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
