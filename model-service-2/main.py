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
    "zero-shot-classification",
    model="valhalla/distilbart-mnli-12-1"
)

PREDICTION_COUNT = Counter("predictions_total", "Total predictions made", ["label"])
PREDICTION_LATENCY = Histogram("prediction_latency_seconds", "Time spent on prediction")
DRIFT_SCORE = Gauge("drift_score", "Latest computed drift score")

CANDIDATE_LABELS = ["technology", "sports", "politics", "entertainment", "business"]
REFERENCE_SIZE = 30
WINDOW_SIZE = 30
reference_data = []
current_window = []

class TextIn(BaseModel):
    text: str
    labels: list[str] = CANDIDATE_LABELS

@app.get("/health")
def health():
    return {"status": "ok", "model": "valhalla/distilbart-mnli-12-1"}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/predict")
def predict(input: TextIn):
    start = time.time()
    result = classifier(input.text, candidate_labels=input.labels)
    latency = time.time() - start
    PREDICTION_LATENCY.observe(latency)
    top_label = result["labels"][0]
    top_score = result["scores"][0]
    PREDICTION_COUNT.labels(label=top_label).inc()

    row = {
        "score": top_score,
        "text_length": len(input.text),
        "num_labels": len(input.labels),
    }
    if len(reference_data) < REFERENCE_SIZE:
        reference_data.append(row)
    else:
        current_window.append(row)
        if len(current_window) >= WINDOW_SIZE:
            compute_drift()

    return {
        "label": top_label,
        "score": round(top_score, 4),
        "all_labels": dict(zip(result["labels"], [round(s, 4) for s in result["scores"]]))
    }

def compute_drift():
    global current_window
    print(f"[drift] computing on {len(reference_data)} reference rows vs {len(current_window)} current rows", flush=True)
    try:
        ref_df = pd.DataFrame(reference_data)
        cur_df = pd.DataFrame(current_window)
        report = Report(metrics=[DataDriftPreset()])
        result = report.run(reference_data=ref_df, current_data=cur_df)
        result_dict = result.dict()
        drift_share = result_dict["metrics"][0]["value"]["share"]
        print(f"[drift] computed drift_share = {drift_share}", flush=True)
        DRIFT_SCORE.set(drift_share)
    except Exception as e:
        import traceback
        print(f"[drift] FAILED: {e}", flush=True)
        traceback.print_exc()
    finally:
        current_window = []

print("[drift] service starting fresh — reference and current windows reset", flush=True)
