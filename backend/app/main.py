from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from backend.app.schemas import Model
from backend.app.db.models import Base
from backend.app.database import engine
from backend.app.services.deployment import deploy_model
from backend.app.services.timeline import build_timeline
from backend.app.services.summary import generate_summary

Base.metadata.create_all(bind=engine)
app = FastAPI()

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

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Model Operations Timeline</title>
  <style>
    body{font-family:monospace;background:#0f0f0f;color:#e0e0e0;padding:2rem;margin:0}
    h1{font-size:1.2rem;color:#7eb8f7;border-bottom:1px solid #333;padding-bottom:.5rem;margin-bottom:1rem}
    #summary-box{
      background:#111;border-left:3px solid #7eb8f7;
      padding:.75rem 1rem;margin-bottom:1.5rem;
      font-size:.85rem;line-height:1.6;color:#ccc;
      min-height:2.5rem;
    }
    #summary-label{font-size:.7rem;color:#555;margin-bottom:.3rem;text-transform:uppercase;letter-spacing:.05em}
    #status{color:#555;font-size:.8rem;margin-bottom:1rem}
    #timeline{list-style:none;padding:0;margin:0}
    #timeline li{display:flex;gap:1rem;align-items:baseline;padding:.35rem 0;border-bottom:1px solid #1a1a1a;font-size:.85rem}
    .ts{color:#555;min-width:180px}
    .badge{display:inline-block;padding:.1rem .5rem;border-radius:3px;font-size:.75rem;min-width:80px;text-align:center}
    .deploy{background:#1a3a5c;color:#7eb8f7}
    .drift{background:#3a1a1a;color:#f77e7e}
    .latency_p95{background:#1a3a1a;color:#7ef7a0}
    .detail{color:#bbb}
  </style>
</head>
<body>
  <h1>Model Operations Timeline</h1>

  <div id="summary-label">LLM Summary</div>
  <div id="summary-box">Loading summary...</div>

  <div id="status">Loading events...</div>
  <ul id="timeline"></ul>

  <script>
    const W = 360;

    function fmt(ts){
      return new Date(ts * 1000).toLocaleString();
    }

    async function loadSummary(){
      const box = document.getElementById('summary-box');
      try {
        const r = await fetch('/summary?window_minutes=' + W);
        const data = await r.json();
        box.textContent = data.summary;
      } catch(err) {
        box.textContent = 'Summary unavailable: ' + err;
      }
    }

    async function loadTimeline(){
      const status = document.getElementById('status');
      const list   = document.getElementById('timeline');
      try {
        const r = await fetch('/timeline?window_minutes=' + W);
        const events = await r.json();
        status.textContent = events.length + ' events — last ' + W + ' min — auto-refresh in 30s';
        list.innerHTML = events.map(e =>
          '<li>' +
          '<span class="ts">' + fmt(e.timestamp) + '</span>' +
          '<span class="badge ' + e.type + '">' + e.type + '</span>' +
          '<span class="detail">' + e.detail + '</span>' +
          '</li>'
        ).join('');
      } catch(err) {
        status.textContent = 'Error loading events: ' + err;
      }
    }

    async function load(){
      await Promise.all([loadSummary(), loadTimeline()]);
    }

    load();
    setInterval(load, 30000);
  </script>
</body>
</html>"""
