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
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST

INPUT_TYPE = os.environ.get("INPUT_TYPE", "text")  # text, json, file

MODEL = None

# Every custom deployment runs this same image, one pod per deployment —
# input_type is the one thing that varies across them and is known at
# startup (see k8s_custom.create_runtime_deployment's env), so it's
# attached as a label on every series here rather than left for someone
# querying Prometheus to have to join against the platform DB to find
# out whether a given series came from a text/json/file model.
#
# predict.py is arbitrary user code (see ../predict_template.py) — unlike
# model-runner/model-service, there's no guaranteed "label" vocabulary,
# so PREDICTION_COUNT/LATENCY are NOT broken down by predicted label the
# way those are: an arbitrary user-supplied label used as a Prometheus
# label value would be unbounded cardinality. The most recent label is
# still tracked, via LAST_PREDICTION (Info's replace-on-set semantics
# keep that to one active series no matter how many distinct labels a
# model has produced over its lifetime).
PREDICTION_COUNT = Counter("predictions_total", "Total predictions", ["input_type"])
PREDICTION_LATENCY = Histogram("prediction_latency_seconds", "Prediction latency", ["input_type"])
PREDICTION_CONFIDENCE = Gauge(
    "prediction_confidence",
    "Confidence score of the most recent prediction — only set when predict.py's result carries a numeric 'score' key",
    ["input_type"],
)
LAST_PREDICTION = Info(
    "last_prediction",
    "input_type and label of the most recently served prediction — label is 'n/a' when predict.py's result doesn't carry one",
)


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


def _extract_confidence(normalized):
    """A numeric 'score' key, if predict.py's result followed that
    convention — None (not 0.0) when it didn't, so callers can leave the
    gauge untouched instead of recording a fabricated confidence."""
    if not isinstance(normalized, dict) or "score" not in normalized:
        return None
    try:
        return float(normalized["score"])
    except (TypeError, ValueError):
        return None


def _extract_label(normalized):
    if not isinstance(normalized, dict) or "label" not in normalized or normalized["label"] is None:
        return None
    return str(normalized["label"])


@app.get("/health")
def health():
    return {"status": "ok", "model_type": "custom", "input_type": INPUT_TYPE}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict")
async def run_predict(request: Request):
    from predict import predict as user_predict

    start = time.time()
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
        normalized = normalize_result(result)

        PREDICTION_COUNT.labels(input_type=INPUT_TYPE).inc()
        PREDICTION_LATENCY.labels(input_type=INPUT_TYPE).observe(time.time() - start)
        confidence = _extract_confidence(normalized)
        if confidence is not None:
            PREDICTION_CONFIDENCE.labels(input_type=INPUT_TYPE).set(confidence)
        label = _extract_label(normalized)
        LAST_PREDICTION.info({"input_type": INPUT_TYPE, "label": label if label is not None else "n/a"})

        return normalized
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
