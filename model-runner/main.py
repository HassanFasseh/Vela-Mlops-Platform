import os
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import pipeline
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
import time

MODEL_NAME = os.environ.get("MODEL_NAME", "distilbert-base-uncased-finetuned-sst-2-english")
TASK_TYPE  = os.environ.get("TASK_TYPE", "sentiment-analysis")

print(f"[runner] loading model={MODEL_NAME} task={TASK_TYPE}", flush=True)
classifier = pipeline(TASK_TYPE, model=MODEL_NAME)
print("[runner] model loaded", flush=True)

app = FastAPI()

PREDICTION_COUNT   = Counter("predictions_total", "Total predictions", ["label"])
PREDICTION_LATENCY = Histogram("prediction_latency_seconds", "Prediction latency")

class TextIn(BaseModel):
    text: str
    labels: list[str] = ["technology", "sports", "politics", "entertainment", "business"]

@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "task": TASK_TYPE}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/predict")
def predict(input: TextIn):
    start = time.time()
    if TASK_TYPE == "zero-shot-classification":
        result = classifier(input.text, candidate_labels=input.labels)
        label  = result["labels"][0]
        score  = result["scores"][0]
        PREDICTION_COUNT.labels(label=label).inc()
        PREDICTION_LATENCY.observe(time.time() - start)
        return {
            "label": label,
            "score": round(score, 4),
            "all_labels": dict(zip(result["labels"], [round(s,4) for s in result["scores"]]))
        }
    else:
        result = classifier(input.text)[0]
        PREDICTION_COUNT.labels(label=result["label"]).inc()
        PREDICTION_LATENCY.observe(time.time() - start)
        return {"label": result["label"], "score": round(result["score"], 4)}
