from fastapi import FastAPI
from pydantic import BaseModel
from transformers import pipeline
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
import time

app = FastAPI()
classifier = pipeline(
    "sentiment-analysis",
    model="distilbert-base-uncased-finetuned-sst-2-english"
)

PREDICTION_COUNT = Counter("predictions_total", "Total predictions made", ["label"])
PREDICTION_LATENCY = Histogram("prediction_latency_seconds", "Time spent on prediction")

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
    PREDICTION_LATENCY.observe(time.time() - start)
    PREDICTION_COUNT.labels(label=result["label"]).inc()
    return {"label": result["label"], "score": round(result["score"], 4)}