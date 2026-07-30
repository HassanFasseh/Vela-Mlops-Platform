from fastapi import FastAPI
from pydantic import BaseModel
from transformers import pipeline
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
import time
import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset

app = FastAPI()
classifier = pipeline(
    "sentiment-analysis",
    model="distilbert-base-uncased-finetuned-sst-2-english"
)

PREDICTION_COUNT = Counter("predictions_total", "Total predictions made", ["label"])
PREDICTION_LATENCY = Histogram("prediction_latency_seconds", "Time spent on prediction")
DRIFT_SCORE = Gauge("drift_score", "Latest computed data drift score (share of drifted columns)")

REFERENCE_SIZE = 30
WINDOW_SIZE = 30
reference_data = []
current_window = []

class TextIn(BaseModel):
    text: str

@app.get("/health")
def health():
    return {"status": "ok"}

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

    if len(reference_data) < REFERENCE_SIZE:
        reference_data.append(row)
    else:
        current_window.append(row)
        if len(current_window) >= WINDOW_SIZE:
            compute_drift()
    print(f"[drift] reference={len(reference_data)} current={len(current_window)}", flush=True)
    return {"label": result["label"], "score": round(result["score"], 4)}

def compute_drift():
    global current_window
    print(f"[drift] computing on {len(reference_data)} reference rows vs {len(current_window)} current rows", flush=True)
    try:
        ref_df = pd.DataFrame(reference_data)
        cur_df = pd.DataFrame(current_window)
        report = Report(metrics=[DataDriftPreset()])
        result = report.run(reference_data=ref_df, current_data=cur_df)
        result_dict = result.dict()
        print(f"[drift] result_dict keys: {result_dict.keys()}", flush=True)
        drift_share = result_dict["metrics"][0]["result"]["drift_share"]
        print(f"[drift] computed drift_share = {drift_share}", flush=True)
        DRIFT_SCORE.set(drift_share)
    except Exception as e:
        import traceback
        print(f"[drift] COMPUTATION FAILED: {e}", flush=True)
        traceback.print_exc()
    finally:
        current_window = []

print(f"[drift] service starting fresh - reference and current windows reset to empty", flush=True)