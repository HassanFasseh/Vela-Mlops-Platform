# Bring-your-own Docker image: the contract

This is what your image needs to implement for Vela's "Docker image" deploy
path (either "Pull from registry" or "Upload image file"). Vela deploys the
image as-is - no build step, no code injected into it - so it's entirely on
the image to speak this contract correctly. It's the same request/response
shapes the "Upload custom model" path already targets (see
`predict_template.py` in this same directory), just self-hosted in your own
container instead of Vela building one for you.

## Requirements

| What | Requirement |
|---|---|
| Port | Listen on `8000`. |
| `GET /health` | Return any 2xx status once the model is loaded and ready to serve. Kubernetes won't consider the pod ready - and Vela won't report the deployment as "running" - until this succeeds. |
| `POST /predict` | See **Request shape** below - it depends on the `input_type` you choose when deploying. |
| `GET /metrics` | Optional, but recommended. Prometheus scrapes this path on port 8000 if present. |

## Request shape

Vela forwards a caller's prediction request to your container's `/predict`
in one of three shapes, matching the `input_type` you picked at deploy time:

| `input_type` | What your container receives |
|---|---|
| `text` | JSON body: `{"text": "..."}` |
| `json` | JSON body: `{"data": {...}}` - any object shape you define, describe it for callers via the optional input schema field |
| `file` | Multipart form with one field named `file` (raw bytes - an image, audio clip, PDF, whatever your model reads) |

## Response shape

Return a JSON-serializable object on success. `{"label": ..., "score": ...}`
gets a colored-badge + confidence-bar treatment in Vela's built-in
prediction tester; any other shape is shown as raw JSON. On failure, return
a non-2xx status - don't return 200 with an error buried in the body.

## Minimal example

A complete FastAPI implementation for `input_type="json"`:

```python
# app.py
from fastapi import FastAPI, Request
import joblib

app = FastAPI()
model = joblib.load("model.joblib")  # loaded once, at import time

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/predict")
async def predict(request: Request):
    body = await request.json()
    features = body["data"]  # shape it however your model needs
    proba = model.predict_proba([list(features.values())])[0]
    top_idx = proba.argmax()
    return {"label": str(model.classes_[top_idx]), "score": float(proba[top_idx])}

@app.get("/metrics")
def metrics():
    return "# no custom metrics yet\n"
```

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn scikit-learn joblib
COPY app.py model.joblib ./
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build it, then either push it somewhere pullable (`docker push ...`) and use
"Pull from registry", or `docker save my-model:tag -o model.tar` and use
"Upload image file" for a fully on-prem deploy with no external registry.
