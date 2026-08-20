from fastapi import FastAPI
from pydantic import BaseModel
from transformers import pipeline
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
import time
import json
import pandas as pd
import redis
from evidently import Report
from evidently.presets import DataDriftPreset

app = FastAPI()

# Redis connection
try:
    import os
    r = redis.Redis(host=os.environ.get('REDIS_HOST', 'redis.default.svc.cluster.local'), port=6379, decode_responses=True)
    r.ping()
    REDIS_AVAILABLE = True
    print("[redis] connected successfully", flush=True)
except Exception as e:
    REDIS_AVAILABLE = False
    print(f"[redis] not available, falling back to in-memory: {e}", flush=True)

REDIS_REF_KEY = "model_service:reference_data"
REDIS_WIN_KEY = "model_service:current_window"

classifier = pipeline(
    "sentiment-analysis",
    model="distilbert-base-uncased-finetuned-sst-2-english"
)

PREDICTION_COUNT = Counter("predictions_total", "Total predictions made", ["label"])
PREDICTION_LATENCY = Histogram("prediction_latency_seconds", "Time spent on prediction")
DRIFT_SCORE = Gauge("drift_score", "Latest computed data drift score")

REFERENCE_SIZE = 30
WINDOW_SIZE = 30
_reference_data = []
_current_window = []

def load_from_redis():
    global _reference_data, _current_window
    if not REDIS_AVAILABLE:
        return
    try:
        ref = r.get(REDIS_REF_KEY)
        win = r.get(REDIS_WIN_KEY)
        if ref:
            _reference_data = json.loads(ref)
            print(f"[redis] loaded {len(_reference_data)} reference rows", flush=True)
        if win:
            _current_window = json.loads(win)
            print(f"[redis] loaded {len(_current_window)} current window rows", flush=True)
    except Exception as e:
        print(f"[redis] load failed: {e}", flush=True)

def save_to_redis():
    if not REDIS_AVAILABLE:
        return
    try:
        r.set(REDIS_REF_KEY, json.dumps(_reference_data))
        r.set(REDIS_WIN_KEY, json.dumps(_current_window))
    except Exception as e:
        print(f"[redis] save failed: {e}", flush=True)

load_from_redis()
print(f"[drift] service started — reference={len(_reference_data)} current={len(_current_window)}", flush=True)

class TextIn(BaseModel):
    text: str

@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": "distilbert-base-uncased-finetuned-sst-2-english",
        "redis": "connected" if REDIS_AVAILABLE else "unavailable",
        "reference_rows": len(_reference_data),
        "current_window_rows": len(_current_window)
    }

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/predict")
def predict(input: TextIn):
    start = time.time()
    result = classifier(input.text)[0]
    latency = time.time() - start
    PREDICTION_LATENCY.observe(latency)
    PREDICTION_COUNT.labels(label=result["label"]).inc()

    row = {
        "score": result["score"],
        "label_encoded": 1 if result["label"] == "POSITIVE" else 0,
        "text_length": len(input.text),
    }

    if len(_reference_data) < REFERENCE_SIZE:
        _reference_data.append(row)
        save_to_redis()
    else:
        _current_window.append(row)
        save_to_redis()
        if len(_current_window) >= WINDOW_SIZE:
            compute_drift()

    print(f"[drift] reference={len(_reference_data)} current={len(_current_window)}", flush=True)
    return {"label": result["label"], "score": round(result["score"], 4)}

def compute_drift():
    global _current_window
    print(f"[drift] computing on {len(_reference_data)} reference rows vs {len(_current_window)} current rows", flush=True)
    try:
        ref_df = pd.DataFrame(_reference_data)
        cur_df = pd.DataFrame(_current_window)
        report = Report(metrics=[DataDriftPreset()])
        result = report.run(reference_data=ref_df, current_data=cur_df)
        result_dict = result.dict()
        drift_share = result_dict["metrics"][0]["value"]["share"]
        print(f"[drift] computed drift_share = {drift_share}", flush=True)
        DRIFT_SCORE.set(drift_share)
    except Exception as e:
        import traceback
        print(f"[drift] COMPUTATION FAILED: {e}", flush=True)
        traceback.print_exc()
    finally:
        _current_window = []
        save_to_redis()
