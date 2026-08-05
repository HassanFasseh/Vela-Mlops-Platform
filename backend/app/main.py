from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from backend.app.schemas import Model
from backend.app.db.models import Base
from backend.app.database import engine
from backend.app.services.deployment import deploy_model
from backend.app.services.timeline import build_timeline

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

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Model Operations Timeline</title>
  <style>
    body{font-family:monospace;background:#0f0f0f;color:#e0e0e0;padding:2rem;margin:0}
    h1{font-size:1.2rem;color:#7eb8f7;border-bottom:1px solid #333;padding-bottom:.5rem}
    #status{color:#888;font-size:.85rem;margin-bottom:1.5rem}
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
  <div id="status">Loading...</div>
  <ul id="timeline"></ul>
  <script>
    const W=360;
    function fmt(ts){return new Date(ts*1000).toLocaleString()}
    async function load(){
      const s=document.getElementById('status');
      const l=document.getElementById('timeline');
      try{
        const r=await fetch('/timeline?window_minutes='+W);
        const ev=await r.json();
        s.textContent=ev.length+' events — last '+W+' min — refreshes in 30s';
        l.innerHTML=ev.map(e=>'<li><span class="ts">'+fmt(e.timestamp)+'</span><span class="badge '+e.type+'">'+e.type+'</span><span class="detail">'+e.detail+'</span></li>').join('');
      }catch(err){s.textContent='Error: '+err}
    }
    load();setInterval(load,30000);
  </script>
</body>
</html>"""
