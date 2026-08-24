"""
Vela custom-model runner — cloud-native variant.

Same interface contract as the original per-deployment-build custom-
runner it replaces (see ../predict_template.py), but predict.py and
model_files/ are no longer baked into the image at build time — this
image is generic and shared by every custom deployment. Per-deployment
content is mounted at runtime instead:

    /app/predict.py       <- ConfigMap volume (sub_path)
    /app/model_files/     <- PersistentVolumeClaim volume

See backend/app/services/k8s_custom.py for exactly how those get
created and mounted.
"""

import base64
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

INPUT_TYPE = os.environ.get("INPUT_TYPE", "text")  # text, json, file

MODEL = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global MODEL
    from predict import load_model

    print(f"[custom-runner] loading model (input_type={INPUT_TYPE})...", flush=True)
    MODEL = load_model("/app/model_files")
    print("[custom-runner] model loaded", flush=True)
    yield


app = FastAPI(lifespan=lifespan)


def _jsonable(value):
    """Coerce common non-JSON-serializable ML return types (numpy scalars,
    torch tensors, ...) to plain Python values. Most of them implement
    .item() for a 0-d/scalar value; anything else that still can't be
    JSON-encoded falls back to its string form rather than 500ing."""
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def normalize_result(result):
    """predict() can return anything — pass it through as-is, but make
    sure it's JSON-safe, and if it already carries "label"/"score" keys
    (the convention every built-in runner in this platform uses) make
    sure those specific values are JSON-safe too, since they're what the
    rest of the platform (monitoring, the sentiment/zero-shot UI on the
    prediction tester) looks for first."""
    if isinstance(result, dict):
        out = {k: _jsonable(v) for k, v in result.items()}
    else:
        out = {"result": _jsonable(result)}
    return out


@app.get("/health")
def health():
    return {"status": "ok", "model_type": "custom", "input_type": INPUT_TYPE}


@app.post("/predict")
async def run_predict(request: Request):
    from predict import predict as user_predict

    try:
        if INPUT_TYPE == "text":
            body = await request.json()
            input_data = body.get("text", "")
        elif INPUT_TYPE == "json":
            body = await request.json()
            input_data = body.get("data", {})
        elif INPUT_TYPE == "file":
            form = await request.form()
            upload = form.get("file")
            if upload is None:
                raise ValueError("Missing 'file' field in multipart form data")
            file_bytes = await upload.read()
            input_data = base64.b64encode(file_bytes).decode("utf-8")
        else:
            raise ValueError(f"Unsupported INPUT_TYPE: {INPUT_TYPE!r} (expected text, json, or file)")

        result = user_predict(MODEL, input_data)
        return normalize_result(result)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
