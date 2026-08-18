from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from backend.app.schemas import Model
from backend.app.db.models import Base
from backend.app.database import engine
from backend.app.services.deployment import deploy_model
from backend.app.services.timeline import build_timeline, build_metrics_summary
from backend.app.services.summary import generate_summary
from pydantic import BaseModel
import requests as http_requests
import os

Base.metadata.create_all(bind=engine)
app = FastAPI()

@app.get("/metrics-summary")
def metrics_summary():
    return build_metrics_summary()

MODEL_SERVICE_URL   = "http://model-service.default.svc.cluster.local"
MODEL_SERVICE_2_URL = "http://model-service-2.default.svc.cluster.local"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")

class PredictRequest(BaseModel):
    text: str
    model_id: int = 0
    service_name: str = ""
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
      const mid=parseInt(document.getElementById('model-select').value);
      if(!text){res.textContent='Enter some text first.';return;}
      btn.disabled=true;res.textContent='Running...';
      try{
        const isSvc=String(mid).startsWith('svc:');
        const body=isSvc?{text,service_name:String(mid).replace('svc:','')}:{text,model_id:parseInt(mid)};
        const r=await fetch('/predict-proxy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        const d=await r.json();
        if(mid===1)res.textContent='Label: '+d.label+' | Score: '+(d.score*100).toFixed(1)+'%';
        else res.textContent='Top: '+d.label+' | '+Object.entries(d.all_labels||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>k+': '+(v*100).toFixed(1)+'%').join(' | ');
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
